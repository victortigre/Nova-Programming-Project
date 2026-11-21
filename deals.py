"""Buying: a buyer asks to buy a listing, the seller accepts, then BOTH sides
confirm the hand-over before it counts as sold.

Like listings.py, every function takes `db` first (the pages pass the real
`database` module, the tests pass the in-memory fake). Permissions are checked
HERE, where the action happens: a buyer may only touch their own request, a
seller only their own listing.

Money (see wallet.py): when the seller accepts, the price is held from the
buyer's Nova credits; when the buyer confirms they got the item, it goes to the
seller; if the deal is called off before that, it goes back to the buyer.
After the buyer has confirmed, the deal can no longer be cancelled.
Once the seller confirms the hand-over, the buyer has 48 hours to either
confirm (money to the seller) or return the item. Without an answer, the money
goes to the seller automatically.

Returning: the buyer gives the item back and taps "I returned the item". The
seller then has 48 hours to confirm they got it back; the buyer is refunded
then, or automatically when the 48 hours pass. Before the hand-over, either
side can simply cancel and the buyer is refunded at once.

A deal (purchase request) moves through these states:
    requested  the buyer asked; the seller hasn't answered
    accepted   the seller picked this buyer; the listing is now Reserved
    declined   the seller said no (or another request was accepted)
    cancelled  either side called it off; the listing goes back to Active
    completed  both sides confirmed the hand-over; the listing is Sold

Changing a status safely: two clicks can arrive at the same moment (a double
click, two browser tabs, the buyer cancelling while the seller accepts). So a
status is never just overwritten. Every change says what the status must still
be, "change this request to accepted, ONLY IF it is still requested", and the
database checks that in the same step as the change. If someone else got there
first, nothing changes and the student sees a message instead.
"""

from datetime import datetime, timedelta, timezone

from accounts import nova_email
import wallet
from listings import ACTIVE, RESERVED, SOLD, ListingError, NotAllowed, NotFound

REQUESTED, ACCEPTED, DECLINED, CANCELLED, COMPLETED = (
    "requested", "accepted", "declined", "cancelled", "completed")
LIVE = (REQUESTED, ACCEPTED)  # a deal still in progress
AUTO_RELEASE_HOURS = 48  # after the seller's hand-over, how long the buyer has to confirm


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
        raise NotFound("This request doesn't exist any more.")
    listing, seller = _own_listing(db, request["listing_id"], seller_email)
    return request, listing, seller


# --- buyer: ask to buy --------------------------------------------------------

def request_to_buy(db, listing_id: int, buyer_email: str) -> dict:
    """Send a request to buy a listing. Returns the new request."""
    buyer = _profile(db, buyer_email)
    listing = _listing(db, listing_id)
    if listing["seller_id"] == buyer["id"]:
        raise NotAllowed("You can't buy your own listing.")
    if listing["status"] == SOLD:
        raise ListingError(["This item is already sold."])
    if listing["status"] != ACTIVE:
        raise ListingError(["This item is reserved for someone else."])
    if db.live_request(buyer["id"], listing_id) is not None:
        raise ListingError(["You already have a request on this item."])
    # Asking is free, but only if you could pay now (the money is held when
    # the seller accepts).
    if not wallet.can_afford(db, buyer["id"], listing.get("price_cents") or 0):
        raise ListingError([wallet.not_enough_message(db, buyer["id"], listing["price_cents"])])
    return db.insert_request({"listing_id": listing_id, "buyer_id": buyer["id"]})


# --- seller: see + answer requests --------------------------------------------

def requests_on_listing(db, listing_id: int, seller_email: str,
                        statuses=LIVE) -> list[dict]:
    """The requests on one of the seller's listings, with the buyer's name added."""
    _own_listing(db, listing_id, seller_email)
    out = []
    for request in db.requests_for_listing(listing_id, list(statuses)):
        buyer = db.get_profile_by_id(request["buyer_id"]) or {}
        out.append({**request, "buyer_name": buyer.get("name", "A student")})
    return out


def accept_request(db, request_id: int, seller_email: str) -> None:
    """Accept one buyer. The listing becomes Reserved; other waiting requests are declined."""
    request, listing, seller = _my_request(db, request_id, seller_email)
    if request["status"] != REQUESTED:
        raise ListingError(["This request can't be accepted any more."])
    if listing["status"] != ACTIVE:
        raise ListingError(["This item isn't available any more."])
    # 1. Reserve the listing, only if it is still active. Of two buyers accepted
    #    at the same moment, only the first one gets this far.
    if not db.update_listing(listing["id"], seller["id"], {"status": RESERVED},
                             only_if_status=ACTIVE):
        raise ListingError(["This item isn't available any more."])
    # 2. Accept the request, only if the buyer hasn't cancelled it meanwhile.
    #    If they have, the listing goes back to active.
    if not db.update_request(request_id, {"status": ACCEPTED}, only_if_status=REQUESTED):
        db.update_listing(listing["id"], seller["id"], {"status": ACTIVE},
                          only_if_status=RESERVED)
        raise ListingError(["This request can't be accepted any more. "
                            "The buyer may have cancelled it."])
    # 3. Hold the price from the buyer's credits. If they don't have enough any
    #    more, undo steps 1 and 2 and tell the seller.
    if not wallet.hold(db, request, listing):
        db.update_request(request_id, {"status": REQUESTED}, only_if_status=ACCEPTED)
        db.update_listing(listing["id"], seller["id"], {"status": ACTIVE},
                          only_if_status=RESERVED)
        raise ListingError(["This buyer doesn't have enough credits any more. "
                            "You can accept another buyer, or wait for them to add credits."])
    # 4. Everyone else who was waiting gets a "no".
    for other in db.requests_for_listing(listing["id"], [REQUESTED]):
        db.update_request(other["id"], {"status": DECLINED}, only_if_status=REQUESTED)


def decline_request(db, request_id: int, seller_email: str) -> None:
    """Say no to a request. If it was the accepted one, the listing goes back to Active."""
    request, listing, seller = _my_request(db, request_id, seller_email)
    if request["status"] not in LIVE:
        raise ListingError(["This request can't be declined any more."])
    if request.get("buyer_confirmed_at"):
        raise ListingError(["The buyer already confirmed they got the item and the "
                            "money is yours, so this can't be declined any more."])
    if request.get("seller_confirmed_at"):
        raise ListingError(["You already handed the item over, so this can't be "
                            "declined any more."])
    if not db.update_request(request_id, {"status": DECLINED},
                             only_if_status=request["status"]):
        raise ListingError(["This request just changed. Please look again."])
    if request["status"] == ACCEPTED:
        wallet.refund(db, request)
        db.update_listing(listing["id"], seller["id"], {"status": ACTIVE},
                          only_if_status=RESERVED)


# --- the two confirmations ----------------------------------------------------

def confirm_sold(db, request_id: int, seller_email: str) -> None:
    """The seller confirms they handed the item over."""
    request, listing, seller = _my_request(db, request_id, seller_email)
    if request["status"] != ACCEPTED:
        raise ListingError(["There's no accepted buyer to confirm with."])
    if not db.update_request(request_id, {"seller_confirmed_at": _now()},
                             only_if_status=ACCEPTED):
        raise ListingError(["This deal isn't active any more."])
    _complete_if_both(db, request_id)


def confirm_received(db, request_id: int, buyer_email: str) -> None:
    """The buyer confirms they received the item."""
    buyer = _profile(db, buyer_email)
    request = db.get_request(request_id)
    if request is None:
        raise NotFound("This request doesn't exist any more.")
    if request["buyer_id"] != buyer["id"]:
        raise NotAllowed("Only the buyer can confirm this.")
    if request["status"] != ACCEPTED:
        raise ListingError(["This deal isn't active any more."])
    if request.get("returned_at"):
        raise ListingError(["You returned this item, so it can't be confirmed any more."])
    if not db.update_request(request_id, {"buyer_confirmed_at": _now()},
                             only_if_status=ACCEPTED):
        raise ListingError(["This deal isn't active any more."])
    # The buyer is happy: the held money goes to the seller.
    wallet.release(db, request, db.get_listing(request["listing_id"]))
    _complete_if_both(db, request_id)


def _complete_if_both(db, request_id: int) -> None:
    """Once BOTH sides have confirmed, mark the deal completed and the listing Sold."""
    request = db.get_request(request_id)
    if not (request["seller_confirmed_at"] and request["buyer_confirmed_at"]):
        return
    # If both confirm at the same moment, only one of them completes the deal.
    if db.update_request(request_id, {"status": COMPLETED}, only_if_status=ACCEPTED):
        listing = db.get_listing(request["listing_id"])
        if listing is not None:
            db.update_listing(listing["id"], listing["seller_id"], {"status": SOLD})


# --- 48 hours after the hand-over: pay the seller automatically ---------------

def _as_time(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def payment_due(request: dict) -> datetime | None:
    """When the seller gets paid automatically, or None if no countdown is running.

    The countdown runs once the seller confirmed the hand-over and the buyer
    hasn't confirmed yet.
    """
    if (request.get("status") != ACCEPTED or request.get("buyer_confirmed_at")
            or request.get("returned_at")):
        return None
    handed_over = _as_time(request.get("seller_confirmed_at"))
    if handed_over is None:
        return None
    return handed_over + timedelta(hours=AUTO_RELEASE_HOURS)


def refund_due(request: dict) -> datetime | None:
    """When a returned item is refunded automatically, or None if no return is running."""
    returned = _as_time(request.get("returned_at"))
    if request.get("status") != ACCEPTED or returned is None:
        return None
    return returned + timedelta(hours=AUTO_RELEASE_HOURS)


def _when(moment: datetime | None) -> str:
    return f"{moment:%a %d %b, %H:%M}" if moment else ""


def due_text(request: dict) -> str:
    """'Sat 22 Nov, 18:05' for the automatic payment, or '' when no countdown runs."""
    return _when(payment_due(request))


def refund_text(request: dict) -> str:
    """'Sat 22 Nov, 18:05' for the automatic refund of a return, or ''."""
    return _when(refund_due(request))


def release_overdue(db, email: str, now: datetime | None = None) -> int:
    """Confirm, for the buyer, every deal of this student whose 48 hours have passed.

    The money goes to the seller and the deal is completed, exactly as if the
    buyer had confirmed. Runs whenever the student opens a page (see to_do), so
    no clock has to run in the background. Returns how many deals it settled.
    """
    now = now or datetime.now(timezone.utc)
    me = _profile(db, email)
    live = db.live_deals_of(me["id"])
    settled = 0
    for request in live["buying"] + live["selling"]:
        due = payment_due(request)
        if due is not None and now >= due:
            # Only if it is still accepted and unconfirmed at this very moment.
            if db.update_request(request["id"], {"buyer_confirmed_at": _now()},
                                 only_if_status=ACCEPTED):
                wallet.release(db, request, db.get_listing(request["listing_id"]))
                _complete_if_both(db, request["id"])
                settled += 1
        refund_at = refund_due(request)
        if refund_at is not None and now >= refund_at:
            # The seller didn't confirm the return in time: refund the buyer.
            if _call_off(db, request, db.get_listing(request["listing_id"])):
                settled += 1
    return settled


# --- the buyer returns the item (within 48 hours of the hand-over) -------------

def return_item(db, request_id: int, buyer_email: str) -> None:
    """The buyer gave the item back. The money stays held; the seller has 48 hours."""
    buyer = _profile(db, buyer_email)
    request = db.get_request(request_id)
    if request is None:
        raise NotFound("This request doesn't exist any more.")
    if request["buyer_id"] != buyer["id"]:
        raise NotAllowed("Only the buyer can return the item.")
    if request["status"] != ACCEPTED or request.get("buyer_confirmed_at"):
        raise ListingError(["This deal is already finished."])
    if not request.get("seller_confirmed_at"):
        raise ListingError(["The seller hasn't handed it over yet. You can simply cancel."])
    if request.get("returned_at"):
        raise ListingError(["You already returned this item."])
    due = payment_due(request)
    if due is not None and datetime.now(timezone.utc) >= due:
        raise ListingError(["The 48 hours have passed, so the payment went to the seller."])
    if not db.update_request(request_id, {"returned_at": _now()}, only_if_status=ACCEPTED):
        raise ListingError(["This deal just changed. Please look again."])


def confirm_return(db, request_id: int, seller_email: str) -> None:
    """The seller got the item back: the buyer is refunded, the listing is active again."""
    request, listing, seller = _my_request(db, request_id, seller_email)
    if request["status"] != ACCEPTED or not request.get("returned_at"):
        raise ListingError(["There's no return to confirm."])
    if not _call_off(db, request, listing):
        raise ListingError(["This deal just changed. Please look again."])


# --- either side: cancel a live deal ------------------------------------------

def cancel_deal(db, request_id: int, email: str) -> None:
    """The buyer or the seller calls off a live deal; the listing goes back to Active."""
    request = db.get_request(request_id)
    if request is None:
        raise NotFound("This request doesn't exist any more.")
    if request["status"] not in LIVE:
        raise ListingError(["This deal can't be cancelled any more."])
    if request.get("buyer_confirmed_at"):
        raise ListingError(["The buyer already confirmed they got the item and the "
                            "money went to the seller, so this deal can't be cancelled."])
    if request.get("seller_confirmed_at"):
        raise ListingError(["The item was already handed over, so the deal can't be "
                            "cancelled. The buyer can return it within 48 hours."])
    person = _profile(db, email)
    listing = db.get_listing(request["listing_id"])
    is_buyer = request["buyer_id"] == person["id"]
    is_seller = listing is not None and listing["seller_id"] == person["id"]
    if not (is_buyer or is_seller):
        raise NotAllowed("Only the buyer or the seller can cancel this deal.")
    if not _call_off(db, request, listing):
        raise ListingError(["This deal just changed. Please look again."])


def _call_off(db, request: dict, listing: dict | None) -> bool:
    """Cancel a live request; if it was the accepted one, the listing is free again."""
    if not db.update_request(request["id"], {"status": CANCELLED},
                             only_if_status=request["status"]):
        return False
    if request["status"] == ACCEPTED:
        wallet.refund(db, request)  # nothing happens if the money was already released
    if request["status"] == ACCEPTED and listing is not None:
        db.update_listing(listing["id"], listing["seller_id"], {"status": ACTIVE},
                          only_if_status=RESERVED)
    return True


def cancel_deals_of(db, profile_id: int) -> None:
    """Call off every live deal of a student an admin just blocked.

    Their own requests are cancelled (an item reserved for them is free again),
    and so are the requests on their listings, so nobody keeps waiting for them.
    Only admin.py calls this, after it checked that an admin is asking.
    """
    for request in db.requests_by_buyer(profile_id, list(LIVE)):
        _call_off(db, request, db.get_listing(request["listing_id"]))
    for request in db.requests_for_seller(profile_id, list(LIVE)):
        _call_off(db, request, db.get_listing(request["listing_id"]))


# --- buyer: my purchases ------------------------------------------------------

def my_purchases(db, buyer_email: str,
                 statuses=(REQUESTED, ACCEPTED, COMPLETED, DECLINED, CANCELLED)) -> list[dict]:
    """The buyer's deals, each with its listing attached, newest first."""
    buyer = _profile(db, buyer_email)
    out = []
    for request in db.requests_by_buyer(buyer["id"], list(statuses)):
        out.append({**request, "listing": db.get_listing(request["listing_id"])})
    return out


# --- seller: my sales -----------------------------------------------------------

def my_sales(db, seller_email: str, statuses=(COMPLETED,)) -> list[dict]:
    """Requests on the seller's listings with these statuses, newest first.

    Each has "title", "price_cents" and "buyer_name" added. Two requests to the
    database in total, however many sales there are.
    """
    seller = _profile(db, seller_email)
    rows = db.requests_for_seller(seller["id"], list(statuses))
    names = db.names_of([row["buyer_id"] for row in rows])
    out = []
    for row in reversed(rows):
        listing = row.get("listings") or {}
        out.append({**row, "title": listing.get("title", ""),
                    "price_cents": listing.get("price_cents", 0),
                    "buyer_name": names.get(row["buyer_id"], "A student")})
    return out


def live_requests_by_listing(db, seller_email: str) -> dict[int, list[dict]]:
    """{listing id: its live requests}, for all of the seller's listings at once."""
    seller = _profile(db, seller_email)
    out = {}
    for row in db.requests_for_seller(seller["id"], list(LIVE)):
        out.setdefault(row["listing_id"], []).append(row)
    return out


# --- what needs your attention (the counts in the menu) -----------------------

def to_do(db, email: str) -> dict[str, int]:
    """How many deals are waiting for this student to do something.

        answer            buyers asked for your item; accept or decline
        confirm_sale      the buyer confirmed they got it; now you confirm
        confirm_received  a seller accepted you; meet them, then confirm
        sales, purchases  the totals for the "Sales" and "My purchases" pages
    """
    me = _profile(db, email)
    release_overdue(db, email)  # 48 hours passed on a hand-over? Pay the seller now.
    live = db.live_deals_of(me["id"])
    answer = sum(1 for r in live["selling"] if r["status"] == REQUESTED)
    confirm_sale = sum(1 for r in live["selling"]
                       if r["status"] == ACCEPTED and r["buyer_confirmed_at"]
                       and not r["seller_confirmed_at"])
    confirm_received = sum(1 for r in live["buying"]
                           if r["status"] == ACCEPTED and not r["buyer_confirmed_at"]
                           and not r.get("returned_at"))
    confirm_return = sum(1 for r in live["selling"]
                         if r["status"] == ACCEPTED and r.get("returned_at"))
    return {"answer": answer, "confirm_sale": confirm_sale,
            "confirm_received": confirm_received, "confirm_return": confirm_return,
            "sales": answer + confirm_sale + confirm_return, "purchases": confirm_received}
