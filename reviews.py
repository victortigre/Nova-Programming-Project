"""Reviews: after a completed deal, the buyer and the seller rate each other.

Feature (area 5, Trust & safety):
    leave_review     rate the other side of a completed deal: 👍 or 👎
    reviewed_deals   which deals this student already rated
    summary          what a profile shows: 👍 and 👎 received, and items sold

Rules that keep this safe:
* Only a COMPLETED deal can be rated: both sides confirmed the hand-over in
  the app, so every rating comes from a real exchange.
* Only the buyer and the seller of that deal can rate it, and each only once
  (the database refuses a second one too, see database_setup.sql).
* You always rate the OTHER side; who that is comes from the deal itself,
  never from the page.
* A rating stays when the listing is deleted later, so a seller can't erase
  a bad one.

Storage: like deals.py, every function takes `db` first: the `database` module
in the pages, the pretend database in the tests (tests/fake_database.py).
"""

from deals import COMPLETED, _profile
from listings import ListingError, NotAllowed, NotFound


def leave_review(db, request_id: int, email: str, positive: bool) -> None:
    """Rate the other side of one of your completed deals (positive = 👍)."""
    me = _profile(db, email)
    request = db.get_request(request_id)
    if request is None:
        raise NotFound("This deal doesn't exist any more.")
    listing = db.get_listing(request["listing_id"])
    if listing is None:
        raise NotFound("This deal doesn't exist any more.")
    if me["id"] == request["buyer_id"]:
        other_id = listing["seller_id"]
    elif me["id"] == listing["seller_id"]:
        other_id = request["buyer_id"]
    else:
        raise NotAllowed("Only the buyer and the seller can rate this deal.")
    if request["status"] != COMPLETED:
        raise ListingError(["You can rate a deal once both of you confirmed the hand-over."])
    if request_id in reviewed_deals(db, email):
        raise ListingError(["You already rated this deal."])
    db.insert_review({"request_id": request_id, "reviewer_id": me["id"],
                      "reviewee_id": other_id, "positive": bool(positive)})


def reviewed_deals(db, email: str) -> dict[int, bool]:
    """{deal (request) id: True for 👍, False for 👎} for every deal this student rated."""
    me = _profile(db, email)
    return {review["request_id"]: review["positive"]
            for review in db.reviews_by(me["id"]) if review["request_id"] is not None}


def summary(db, profile_id: int) -> dict[str, int]:
    """{"positive": 👍 received, "negative": 👎 received, "sold": completed sales}."""
    received = db.reviews_about(profile_id)
    positive = sum(1 for review in received if review["positive"])
    sold = len(db.requests_for_seller(profile_id, [COMPLETED]))
    return {"positive": positive, "negative": len(received) - positive, "sold": sold}
