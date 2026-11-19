"""Buying: a buyer asks to buy a listing, the seller accepts, then BOTH sides
confirm the hand-over before it counts as sold.

Like listings.py, every function takes `db` first (the pages pass the real
`database` module, the tests pass the in-memory fake). Permissions are checked
HERE, where the action happens: a buyer may only touch their own request, a
seller only their own listing.

A deal (purchase request) moves through these states:
    requested  the buyer asked; the seller hasn't answered
    accepted   the seller picked this buyer; the listing is now Reserved
    declined   the seller said no (or another request was accepted)
    cancelled  either side called it off; the listing goes back to Active
    completed  both sides confirmed the hand-over; the listing is Sold
"""

from datetime import datetime, timezone

from accounts import nova_email
from listings import ACTIVE, RESERVED, SOLD, ListingError, NotAllowed, NotFound

REQUESTED, ACCEPTED, DECLINED, CANCELLED, COMPLETED = (
    "requested", "accepted", "declined", "cancelled", "completed")
LIVE = (REQUESTED, ACCEPTED)  # a deal still in progress


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile(db, email: str) -> dict:
    who = nova_email({"email": email})
    if who is None:
        raise NotAllowed("Only @novasbe.pt accounts can do this.")
    profile = db.get_profile(who)
    if profile is None:
        raise NotAllowed("Fill in your profile first.")
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
    if db.live_request(buyer["id"], listing_id) is not None:
        raise ListingError(["You already have a request on this item."])
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
    db.update_request(request_id, {"status": ACCEPTED})
    db.update_listing(listing["id"], seller["id"], {"status": RESERVED})
    for other in db.requests_for_listing(listing["id"], [REQUESTED]):
        if other["id"] != request_id:
            db.update_request(other["id"], {"status": DECLINED})


def decline_request(db, request_id: int, seller_email: str) -> None:
    """Say no to a request. If it was the accepted one, the listing goes back to Active."""
    request, listing, seller = _my_request(db, request_id, seller_email)
    if request["status"] not in LIVE:
        raise ListingError(["This request can't be declined any more."])
    db.update_request(request_id, {"status": DECLINED})
    if request["status"] == ACCEPTED and listing["status"] == RESERVED:
        db.update_listing(listing["id"], seller["id"], {"status": ACTIVE})


# --- the two confirmations ----------------------------------------------------

def confirm_sold(db, request_id: int, seller_email: str) -> None:
    """The seller confirms they handed the item over."""
    request, listing, seller = _my_request(db, request_id, seller_email)
    if request["status"] != ACCEPTED:
        raise ListingError(["There's no accepted buyer to confirm with."])
    db.update_request(request_id, {"seller_confirmed_at": _now()})
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
    db.update_request(request_id, {"buyer_confirmed_at": _now()})
    _complete_if_both(db, request_id)


def _complete_if_both(db, request_id: int) -> None:
    """Once BOTH sides have confirmed, mark the listing Sold and the deal completed."""
    request = db.get_request(request_id)
    if request["seller_confirmed_at"] and request["buyer_confirmed_at"]:
        listing = db.get_listing(request["listing_id"])
        if listing is not None:
            db.update_listing(listing["id"], listing["seller_id"], {"status": SOLD})
        db.update_request(request_id, {"status": COMPLETED})


# --- either side: cancel a live deal ------------------------------------------

def cancel_deal(db, request_id: int, email: str) -> None:
    """The buyer or the seller calls off a live deal; the listing goes back to Active."""
    request = db.get_request(request_id)
    if request is None:
        raise NotFound("This request doesn't exist any more.")
    if request["status"] not in LIVE:
        raise ListingError(["This deal can't be cancelled any more."])
    person = _profile(db, email)
    listing = db.get_listing(request["listing_id"])
    is_buyer = request["buyer_id"] == person["id"]
    is_seller = listing is not None and listing["seller_id"] == person["id"]
    if not (is_buyer or is_seller):
        raise NotAllowed("Only the buyer or the seller can cancel this deal.")
    db.update_request(request_id, {"status": CANCELLED})
    if request["status"] == ACCEPTED and listing is not None and listing["status"] == RESERVED:
        db.update_listing(listing["id"], listing["seller_id"], {"status": ACTIVE})


# --- buyer: my purchases ------------------------------------------------------

def my_purchases(db, buyer_email: str,
                 statuses=(REQUESTED, ACCEPTED, COMPLETED)) -> list[dict]:
    """The buyer's deals, each with its listing attached, newest first."""
    buyer = _profile(db, buyer_email)
    out = []
    for request in db.requests_by_buyer(buyer["id"], list(statuses)):
        out.append({**request, "listing": db.get_listing(request["listing_id"])})
    return out
