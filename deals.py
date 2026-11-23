"""Buying: Buy Now, the buyer pays the seller directly, the seller confirms.

The app never moves money. Students pay each other in one of the ways the
seller accepts (payments.py): bank transfer (IBAN) or cash in person:

  1. The buyer taps "Buy now" on the item page at the listed price
     (buy_at_listed_price), or first agrees a lower price in the chat (an
     accepted offer) and taps "Buy Now" there (buy_now). The deal starts, the
     listing becomes Reserved, and the chat shows how to pay the seller.
  2. The buyer has 15 minutes to pay and tap "I've paid with …" (mark_paid,
     saying which method). If they don't, the deal is cancelled automatically
     and the item is back on sale (cancel_overdue, run whenever a student
     opens a page: no clock needed). Cash is different: the buyer chooses
     "Pay in cash when we meet" (choose_cash) and there is no deadline.
  3. The seller checks (their bank, app, or the cash in hand) and taps "Payment received"
     (confirm_payment): the deal is completed and the listing is Sold.
     If the money isn't there, "Not received yet" (payment_not_received) sends
     it back to the buyer, who checks and taps "I've paid" again. They sort
     it out in the chat; the seller can cancel the deal if it never arrives.

Before the buyer says they paid, either side can cancel. After that, only
the seller can end it: by confirming, or by saying it didn't arrive first.

Like listings.py, every function takes `db` first (the pages pass the real
`database` module, the tests pass the in-memory fake). Permissions are checked
HERE, where the action happens: a buyer may only touch their own deal, a
seller only their own listing.

A deal (purchase request) moves through these states:
    accepted   Buy Now was tapped; waiting for the payment; listing Reserved
    completed  the seller confirmed the payment; the listing is Sold
    cancelled  called off (by a student, or 15 minutes without payment); Active
    requested, declined   only in deals from the earlier "Request to buy"

Changing a status safely: two clicks can arrive at the same moment (a double
click, two browser tabs). So a status is never just overwritten. Every change
says what the status must still be ("change it to completed ONLY IF it is
still accepted") and the database checks that in the same step.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import payments
from accounts import nova_email
from listings import ACTIVE, RESERVED, SOLD, ListingError, NotAllowed, NotFound, expired, format_price

REQUESTED, ACCEPTED, DECLINED, CANCELLED, COMPLETED = (
    "requested", "accepted", "declined", "cancelled", "completed")
LIVE = (REQUESTED, ACCEPTED)  # a deal still in progress
PAY_WITHIN_MINUTES = 15  # after Buy Now, how long the buyer has to pay


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile(db, email: str) -> dict:
    who = nova_email({"email": email})
    if who is None:
        raise NotAllowed("Only @novasbe.pt accounts can do this.")
    profile = db.get_profile(who)
    if profile is None:
        raise NotAllowed("Fill in your profile first.")
    if profile.get("blocked_at"):  # an admin blocked this student (see admin.py)
        raise NotAllowed("Your account has been blocked.")
    return profile


def _listing(db, listing_id: int) -> dict:
    listing = db.get_listing(listing_id)
    if listing is None:
        raise NotFound("This listing doesn't exist any more.")
    return listing


def _own_listing(db, listing_id: int, seller_email: str) -> tuple[dict, dict]:
    seller = _profile(db, seller_email)
    listing = _listing(db, listing_id)
    if listing["seller_id"] != seller["id"]:
        raise NotAllowed("Only the seller can do this.")
    return listing, seller


def _my_request(db, request_id: int, seller_email: str) -> tuple[dict, dict, dict]:
    """(request, listing, seller) when the listing belongs to this seller."""
    request = db.get_request(request_id)
    if request is None:
        raise NotFound("This deal doesn't exist any more.")
    listing, seller = _own_listing(db, request["listing_id"], seller_email)
    return request, listing, seller


def _my_purchase(db, request_id: int, buyer_email: str) -> tuple[dict, dict]:
    """(request, buyer) when this student is the buyer."""
    buyer = _profile(db, buyer_email)
    request = db.get_request(request_id)
    if request is None:
        raise NotFound("This deal doesn't exist any more.")
    if request["buyer_id"] != buyer["id"]:
        raise NotAllowed("Only the buyer can do this.")
    return request, buyer


def price_of(request: dict, listing: dict | None = None) -> int:
    """The agreed price in cents (or the listing's price for older deals)."""
    if request.get("agreed_price_cents") is not None:
        return request["agreed_price_cents"]
    listing = listing or request.get("listing") or request.get("listings") or {}
    return listing.get("price_cents") or 0


# --- 1. buyer: Buy Now (after a price was agreed in the chat) ------------------

def buy_now(db, buyer_email: str, conversation_id: str) -> dict:
    """Start the purchase at the price agreed in this chat (an accepted offer)."""
    buyer, chat = _buyers_chat(db, buyer_email, conversation_id)
    offers = db.messaging_offers(conversation_id, 1, 0)
    if not offers or offers[0]["status"] != "accepted":
        raise ListingError(["Agree a price in the chat first: an offer must be accepted."])
    return _start_purchase(db, buyer, chat, offers[0]["amount_cents"])


def buy_at_listed_price(db, buyer_email: str, conversation_id: str) -> dict:
    """Buy now from the item page: the listed price, no offer needed.

    The page first opens (or reuses) the chat with the seller, so the payment
    details and the conversation live in one place, like after an offer.
    """
    buyer, chat = _buyers_chat(db, buyer_email, conversation_id)
    listing = _listing(db, chat["listing_id"])
    price = listing.get("price_cents") or 0
    if price <= 0:
        raise ListingError(["This item is free: there's nothing to pay. "
                            "Contact the seller to arrange the pickup."])
    # A price the two already agreed in the chat counts, wherever Buy Now is tapped.
    offers = db.messaging_offers(chat["id"], 1, 0)
    if offers and offers[0]["status"] == "accepted":
        price = offers[0]["amount_cents"]
    return _start_purchase(db, buyer, chat, price)


def _buyers_chat(db, buyer_email: str, conversation_id: str) -> tuple[dict, dict]:
    """(buyer, chat) when this student is the buyer in this chat about a listing."""
    buyer = _profile(db, buyer_email)
    chat = db.messaging_conversation(conversation_id, buyer["id"])
    if chat is None or chat["buyer_id"] != buyer["id"]:
        raise NotAllowed("Only the buyer in this chat can use Buy Now.")
    if chat.get("listing_id") is None:
        raise ListingError(["This listing doesn't exist any more."])
    return buyer, chat


def _start_purchase(db, buyer: dict, chat: dict, price_cents: int) -> dict:
    """Reserve the listing and create the deal: 15 minutes to pay `price_cents`."""
    listing = _listing(db, chat["listing_id"])
    if listing["seller_id"] != chat["seller_id"]:
        raise ListingError(["This listing changed hands. Please look again."])
    # Asked first: the buyer's own purchase is what reserved the item.
    if db.live_request(buyer["id"], listing["id"]) is not None:
        raise ListingError(["You already started buying this item."])
    if listing["status"] == SOLD:
        raise ListingError(["This item is already sold."])
    if listing["status"] != ACTIVE:
        raise ListingError(["This item is reserved for someone else."])
    if expired(listing, date.today()):
        raise ListingError(["The seller's \"available until\" date has passed, "
                            "so this item can't be bought any more."])
    seller = db.get_profile_by_id(listing["seller_id"])
    # A blocked seller could not confirm the payment, so the deal would be stuck.
    if seller is None or seller.get("blocked_at"):
        raise ListingError(["This seller isn't available any more, so the item can't be bought."])
    if not payments.can_be_paid(seller):
        raise ListingError(["The seller hasn't added a way to get paid yet, so you can't "
                            "pay them. Ask them in the chat to add one on My profile."])
    # Reserve first, only if it is still active: of two Buy Now taps at the same
    # moment, only one gets past this line.
    if not db.update_listing(listing["id"], listing["seller_id"], {"status": RESERVED},
                             only_if_status=ACTIVE):
        raise ListingError(["This item isn't available any more."])
    pay_by = datetime.now(timezone.utc) + timedelta(minutes=PAY_WITHIN_MINUTES)
    row = {
        "listing_id": listing["id"], "buyer_id": buyer["id"], "status": ACCEPTED,
        "agreed_price_cents": price_cents, "conversation_id": chat["id"],
        "pay_by": pay_by.isoformat(),
    }
    # A seller who only takes cash: the buyer pays when they meet, so there is
    # nothing to choose and no 15-minute deadline (it would cancel the deal).
    if [m["key"] for m in payments.methods_of(seller)] == [payments.CASH]:
        row["payment_method"] = payments.CASH
    try:
        return db.insert_request(row)
    except Exception:
        # The purchase could not be saved (for example the connection dropped).
        # Without this the item would stay reserved for nobody.
        db.update_listing(listing["id"], listing["seller_id"], {"status": ACTIVE},
                          only_if_status=RESERVED)
        raise


def deal_in_chat(db, email: str, conversation_id: str) -> dict | None:
    """The newest deal started from this chat, if this student is its buyer or seller."""
    me = _profile(db, email)
    request = db.request_for_conversation(conversation_id)
    if request is None:
        return None
    listing = db.get_listing(request["listing_id"])
    if request["buyer_id"] != me["id"] and (listing is None or listing["seller_id"] != me["id"]):
        return None
    return {**request, "listing": listing}


def payment_details(db, request_id: int, email: str) -> dict:
    """How to pay: {"methods", "amount_cents", "reference", "pay_by", "method"}.

    "methods" are the seller's accepted methods with their details (see
    payments.methods_of); "method" is the one the buyer chose, if any.
    Only the buyer and the seller of this deal may see them.
    """
    me = _profile(db, email)
    request = db.get_request(request_id)
    if request is None:
        raise NotFound("This deal doesn't exist any more.")
    listing = _listing(db, request["listing_id"])
    if me["id"] not in (request["buyer_id"], listing["seller_id"]):
        raise NotAllowed("Only the buyer and the seller can see the payment details.")
    seller = db.get_profile_by_id(listing["seller_id"]) or {}
    return {"methods": payments.methods_of(seller),
            "amount_cents": price_of(request, listing),
            "reference": f"Nova Marketplace #{request['id']}",
            "pay_by": pay_by_text(request),
            "method": request.get("payment_method")}


def _sellers_methods(db, request: dict) -> list[str]:
    listing = _listing(db, request["listing_id"])
    return [m["key"] for m in payments.methods_of(db.get_profile_by_id(listing["seller_id"]))]


# --- 2. buyer: I've paid ---------------------------------------------------------

def _announce_paid(db, request: dict) -> None:
    """Drop a line in the chat when the buyer says they paid, so the seller's
    Inbox shows it as unread too (the Browse notice already fires). Best-effort:
    a messaging hiccup must never undo the recorded payment."""
    if not request.get("conversation_id"):
        return
    amount = format_price(request.get("agreed_price_cents") or 0)
    try:
        db.messaging_insert_message({
            "conversation_id": request["conversation_id"],
            "sender_id": request["buyer_id"],
            "client_message_id": str(uuid4()),
            "body": f"✅ I've paid {amount}. Please confirm you received it.",
        })
    except Exception:
        pass


def mark_paid(db, request_id: int, buyer_email: str, method: str | None = None) -> None:
    """The buyer says they paid, and how (one of the seller's methods).
    The seller is asked to check."""
    request, _ = _my_purchase(db, request_id, buyer_email)
    if request["status"] != ACCEPTED:
        raise ListingError(["This deal isn't active any more."])
    if request.get("paid_at"):
        raise ListingError(["You already said you paid. The seller is checking."])
    due = pay_due(request)
    if due is not None and datetime.now(timezone.utc) >= due:
        raise ListingError(["The 15 minutes to pay have passed, so the deal was cancelled."])
    method = method or request.get("payment_method")
    if method not in _sellers_methods(db, request):
        raise ListingError(["Choose how you paid: one of the ways the seller accepts."])
    if not db.update_request(request_id, {"paid_at": _now(), "payment_missing_at": None,
                                          "payment_method": method},
                             only_if_status=ACCEPTED):
        raise ListingError(["This deal just changed. Please look again."])
    _announce_paid(db, request)  # so the seller's Inbox lights up, not only Browse


def choose_cash(db, request_id: int, buyer_email: str) -> None:
    """The buyer will pay in cash when they meet. No 15-minute deadline for cash."""
    request, _ = _my_purchase(db, request_id, buyer_email)
    if request["status"] != ACCEPTED or request.get("paid_at"):
        raise ListingError(["This deal isn't waiting for a payment."])
    if payments.CASH not in _sellers_methods(db, request):
        raise ListingError(["This seller doesn't accept cash."])
    due = pay_due(request)
    if due is not None and datetime.now(timezone.utc) >= due:
        raise ListingError(["The 15 minutes to pay have passed, so the deal was cancelled."])
    if not db.update_request(request_id, {"payment_method": payments.CASH},
                             only_if_status=ACCEPTED):
        raise ListingError(["This deal just changed. Please look again."])


def paying_cash(request: dict) -> bool:
    """Did the buyer choose to pay in cash when they meet?"""
    return request.get("payment_method") == payments.CASH


# --- 3. seller: check the bank ------------------------------------------------------

def confirm_payment(db, request_id: int, seller_email: str) -> None:
    """The money arrived: the deal is completed and the listing is Sold."""
    request, listing, seller = _my_request(db, request_id, seller_email)
    if request["status"] != ACCEPTED:
        raise ListingError(["This deal isn't active any more."])
    if not request.get("paid_at") and not paying_cash(request):
        raise ListingError(["The buyer hasn't said they paid yet."])
    if not db.update_request(request_id, {"status": COMPLETED, "seller_confirmed_at": _now()},
                             only_if_status=ACCEPTED):
        raise ListingError(["This deal just changed. Please look again."])
    db.update_listing(listing["id"], seller["id"], {"status": SOLD})


def payment_not_received(db, request_id: int, seller_email: str) -> None:
    """The money isn't there (yet). The buyer is asked to check and confirm again."""
    request, _, _ = _my_request(db, request_id, seller_email)
    if request["status"] != ACCEPTED or not request.get("paid_at"):
        raise ListingError(["There's no payment to check."])
    if not db.update_request(request_id, {"paid_at": None, "payment_missing_at": _now()},
                             only_if_status=ACCEPTED):
        raise ListingError(["This deal just changed. Please look again."])


# --- the 15 minutes to pay ----------------------------------------------------------

def _as_time(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def pay_due(request: dict) -> datetime | None:
    """When an unpaid deal is cancelled automatically, or None if no countdown runs.

    The countdown stops once the buyer says they paid. After a "not received
    yet" it doesn't come back: the two talk, and the seller may cancel.
    """
    if (request.get("status") != ACCEPTED or request.get("paid_at")
            or request.get("payment_missing_at") or paying_cash(request)):
        return None  # paid, being sorted out, or cash when they meet: no deadline
    return _as_time(request.get("pay_by"))


def pay_by_text(request: dict) -> str:
    """'Sat 22 Nov, 18:05': the last moment to pay, or ''."""
    due = pay_due(request)
    # Shown in Lisbon time, so "16:20" is the time on the student's clock.
    return f"{due.astimezone(ZoneInfo('Europe/Lisbon')):%a %d %b, %H:%M}" if due else ""


def cancel_overdue(db, email: str, now: datetime | None = None) -> int:
    """Cancel this student's deals whose 15 minutes to pay have passed.

    Runs whenever the student opens a page (see to_do), so no clock has to run
    in the background. Returns how many deals it cancelled.
    """
    now = now or datetime.now(timezone.utc)
    me = _profile(db, email)
    live = db.live_deals_of(me["id"])
    cancelled = 0
    for request in live["buying"] + live["selling"]:
        due = pay_due(request)
        if due is not None and now >= due:
            fresh = db.get_request(request["id"])
            if fresh and pay_due(fresh) is not None and now >= pay_due(fresh):
                if _call_off(db, fresh, db.get_listing(fresh["listing_id"])):
                    cancelled += 1
    return cancelled


# --- cancelling ---------------------------------------------------------------------

def cancel_all_overdue(db, now: datetime | None = None) -> int:
    """Cancel every deal whose 15 minutes to pay have passed, whoever it belongs to.

    cancel_overdue above only runs when the buyer or the seller opens the app.
    Browse calls this one, so an unpaid item comes back on sale for everybody.
    """
    now = now or datetime.now(timezone.utc)
    cancelled = 0
    for request in db.unpaid_deals_due_before(now.isoformat()):
        due = pay_due(request)
        if due is not None and now >= due:
            if _call_off(db, request, db.get_listing(request["listing_id"])):
                cancelled += 1
    return cancelled


def cancel_deal(db, request_id: int, email: str) -> None:
    """Call off a live deal; the listing goes back to Active.

    Before the buyer says they paid, either side may. After that only the
    seller may, once they said the payment didn't arrive.
    """
    request = db.get_request(request_id)
    if request is None:
        raise NotFound("This deal doesn't exist any more.")
    if request["status"] not in LIVE:
        raise ListingError(["This deal can't be cancelled any more."])
    person = _profile(db, email)
    listing = db.get_listing(request["listing_id"])
    is_buyer = request["buyer_id"] == person["id"]
    is_seller = listing is not None and listing["seller_id"] == person["id"]
    if not (is_buyer or is_seller):
        raise NotAllowed("Only the buyer or the seller can cancel this deal.")
    if request.get("paid_at"):
        raise ListingError(["The buyer says they paid. The seller must first check the "
                            "bank: confirm the payment, or say it didn't arrive."])
    if is_buyer and request.get("payment_missing_at"):
        raise ListingError(["The seller says the payment didn't arrive. Check with your "
                            "bank and talk to them in the chat."])
    if not _call_off(db, request, listing):
        raise ListingError(["This deal just changed. Please look again."])


def decline_request(db, request_id: int, seller_email: str) -> None:
    """Say no to an old "Request to buy" that is still waiting."""
    request, listing, seller = _my_request(db, request_id, seller_email)
    if request["status"] != REQUESTED:
        raise ListingError(["This request can't be declined any more."])
    if not db.update_request(request_id, {"status": DECLINED}, only_if_status=REQUESTED):
        raise ListingError(["This request just changed. Please look again."])


def _call_off(db, request: dict, listing: dict | None) -> bool:
    """Cancel a live deal; if it had reserved the listing, the listing is free again."""
    if not db.update_request(request["id"], {"status": CANCELLED},
                             only_if_status=request["status"]):
        return False
    if request["status"] == ACCEPTED and listing is not None:
        db.update_listing(listing["id"], listing["seller_id"], {"status": ACTIVE},
                          only_if_status=RESERVED)
    return True


def cancel_deals_of(db, profile_id: int) -> None:
    """Call off every live deal of a student an admin just blocked.

    Only admin.py calls this, after it checked that an admin is asking.
    """
    for request in db.requests_by_buyer(profile_id, list(LIVE)):
        _call_off(db, request, db.get_listing(request["listing_id"]))
    for request in db.requests_for_seller(profile_id, list(LIVE)):
        _call_off(db, request, db.get_listing(request["listing_id"]))


# --- lists for the pages ---------------------------------------------------------------

def requests_on_listing(db, listing_id: int, seller_email: str,
                        statuses=LIVE) -> list[dict]:
    """The deals on one of the seller's listings, with the buyer's name added."""
    _own_listing(db, listing_id, seller_email)
    out = []
    for request in db.requests_for_listing(listing_id, list(statuses)):
        buyer = db.get_profile_by_id(request["buyer_id"]) or {}
        out.append({**request, "buyer_name": buyer.get("name", "A student")})
    return out


def my_purchases(db, buyer_email: str,
                 statuses=(REQUESTED, ACCEPTED, COMPLETED, DECLINED, CANCELLED)) -> list[dict]:
    """The buyer's deals, newest first. Each has its "listing" attached (None if
    it was removed) and the "seller_name" (None if unknown).

    All listings come in one request and all names in another, however many
    deals there are.
    """
    buyer = _profile(db, buyer_email)
    requests = db.requests_by_buyer(buyer["id"], list(statuses))
    listings = db.listings_by_ids([request["listing_id"] for request in requests])
    names = db.names_of([listing["seller_id"] for listing in listings.values()])
    out = []
    for request in requests:
        listing = listings.get(request["listing_id"])
        out.append({**request, "listing": listing,
                    "seller_name": names.get(listing["seller_id"]) if listing else None})
    return out


def my_sales(db, seller_email: str, statuses=(COMPLETED,)) -> list[dict]:
    """Deals on the seller's listings with these statuses, newest first.

    Each has "title", "price_cents" (the agreed price) and "buyer_name" added.
    """
    seller = _profile(db, seller_email)
    rows = db.requests_for_seller(seller["id"], list(statuses))
    names = db.names_of([row["buyer_id"] for row in rows])
    out = []
    for row in reversed(rows):
        listing = row.get("listings") or {}
        out.append({**row, "title": listing.get("title", ""),
                    "price_cents": price_of(row, listing),
                    "buyer_name": names.get(row["buyer_id"], "A student")})
    return out


def live_requests_by_listing(db, seller_email: str) -> dict[int, list[dict]]:
    """{listing id: its live deals}, for all of the seller's listings at once."""
    seller = _profile(db, seller_email)
    rows = db.requests_for_seller(seller["id"], list(LIVE))
    names = db.names_of([row["buyer_id"] for row in rows])
    out = {}
    for row in rows:
        out.setdefault(row["listing_id"], []).append(
            {**row, "buyer_name": names.get(row["buyer_id"], "A student")})
    return out


# --- what needs your attention (the counts in the menu) -----------------------------

def to_do(db, email: str) -> dict[str, int]:
    """How many deals are waiting for this student to do something.

        pay            you tapped Buy Now: pay and tap "I've paid"
        check_payment  a buyer says they paid: check your bank and confirm
        answer         old "Request to buy" requests still waiting for you
        sales, purchases  the totals for the "My listings" and "My purchases" pages
    """
    me = _profile(db, email)
    cancel_overdue(db, email)  # 15 minutes without payment? Cancel those first.
    live = db.live_deals_of(me["id"])
    pay = sum(1 for r in live["buying"] if r["status"] == ACCEPTED and not r.get("paid_at"))
    check = sum(1 for r in live["selling"]
                if r["status"] == ACCEPTED and (r.get("paid_at") or paying_cash(r)))
    answer = sum(1 for r in live["selling"] if r["status"] == REQUESTED)
    return {"pay": pay, "check_payment": check, "answer": answer,
            "sales": check + answer, "purchases": pay}


def waiting_on_me(db, email: str) -> dict[str, list[dict]]:
    """The deals behind to_do's "pay" and "check_payment", with names, for the
    notifications on Browse ("Maria says she paid you €20.00").

        pay            [{"request_id", "seller_name", "title", "price_cents", "cash", "at"}]
        check_payment  [{"request_id", "buyer_name", "title", "price_cents", "cash", "paid",
                         "at"}]

    "at" is when it last happened (Buy Now, or "I've paid"), to show the newest first.
    """
    me = _profile(db, email)
    live = db.live_deals_of(me["id"])
    selling = [r for r in live["selling"]
               if r["status"] == ACCEPTED and (r.get("paid_at") or paying_cash(r))]
    buying = [r for r in live["buying"] if r["status"] == ACCEPTED and not r.get("paid_at")]
    listings_of = {r["id"]: (r.get("listings") or db.get_listing(r["listing_id"]) or {})
                   for r in selling + buying}
    names = db.names_of([r["buyer_id"] for r in selling]
                        + [listings_of[r["id"]].get("seller_id") for r in buying])
    check = [{"request_id": r["id"], "buyer_name": names.get(r["buyer_id"], "A student"),
              "title": listings_of[r["id"]].get("title", "your item"),
              "price_cents": price_of(r, listings_of[r["id"]]),
              "cash": paying_cash(r), "paid": bool(r.get("paid_at")),
              "at": r.get("paid_at") or r.get("created_at")} for r in selling]
    pay = [{"request_id": r["id"],
            "seller_name": names.get(listings_of[r["id"]].get("seller_id"), "the seller"),
            "title": listings_of[r["id"]].get("title", "an item"),
            "price_cents": price_of(r, listings_of[r["id"]]),
            "cash": paying_cash(r), "at": r.get("created_at")} for r in buying]
    return {"pay": pay, "check_payment": check}
