"""Reviews: after a completed deal, the buyer and the seller rate each other.

Feature (area 5, Trust & safety):
    leave_review     rate the other side of a completed deal: 1 to 5 stars,
                     plus an optional written feedback
    reviewed_deals   which deals this student already rated (and how)
    summary          what a profile shows: average stars, number of ratings,
                     items sold
    recent_feedback  the latest ratings with their written feedback

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

MAX_COMMENT_LENGTH = 500


def stars_of(review: dict) -> int:
    """1 to 5. Ratings from before stars existed were 👍 or 👎: they count as 5 or 1."""
    if review.get("stars"):
        return int(review["stars"])
    return 5 if review.get("positive") else 1


def check_review(stars, comment) -> list[str]:
    errors = []
    if not isinstance(stars, int) or isinstance(stars, bool) or not 1 <= stars <= 5:
        errors.append("Choose from 1 to 5 stars.")
    if len((comment or "").strip()) > MAX_COMMENT_LENGTH:
        errors.append(f"Feedback can be at most {MAX_COMMENT_LENGTH} characters.")
    return errors


def leave_review(db, request_id: int, email: str, stars: int, comment: str = "") -> None:
    """Rate the other side of one of your completed deals: 1 to 5 stars, optional feedback."""
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
    errors = check_review(stars, comment)
    if errors:
        raise ListingError(errors)
    db.insert_review({"request_id": request_id, "reviewer_id": me["id"],
                      "reviewee_id": other_id, "stars": stars,
                      "comment": (comment or "").strip() or None,
                      "positive": stars >= 3})  # kept for the older 👍/👎 column


def reviewed_deals(db, email: str) -> dict[int, dict]:
    """{deal (request) id: {"stars": 1-5, "comment": text or None}} for every deal rated."""
    me = _profile(db, email)
    return {review["request_id"]: {"stars": stars_of(review), "comment": review.get("comment")}
            for review in db.reviews_by(me["id"]) if review["request_id"] is not None}


def summary(db, profile_id: int) -> dict:
    """{"average": e.g. 4.5 (None without ratings), "count": ratings, "sold": completed sales}."""
    received = db.reviews_about(profile_id)
    stars = [stars_of(review) for review in received]
    sold = len(db.requests_for_seller(profile_id, [COMPLETED]))
    average = round(sum(stars) / len(stars), 1) if stars else None
    return {"average": average, "count": len(stars), "sold": sold}


def recent_feedback(db, profile_id: int, limit: int = 5) -> list[dict]:
    """The latest ratings about this student that have written feedback, newest first.

    Each: {"stars", "comment", "reviewer_name"}.
    """
    received = [r for r in db.reviews_about(profile_id) if (r.get("comment") or "").strip()]
    received.sort(key=lambda r: (str(r.get("created_at") or ""), r.get("id") or 0), reverse=True)
    received = received[:limit]
    names = db.names_of([r["reviewer_id"] for r in received])
    return [{"stars": stars_of(r), "comment": r["comment"].strip(),
             "reviewer_name": names.get(r["reviewer_id"], "A student")} for r in received]


def star_text(stars: int) -> str:
    """4 -> '★★★★☆'."""
    return "★" * stars + "☆" * (5 - stars)
