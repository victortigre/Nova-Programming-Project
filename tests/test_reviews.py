"""Tests for ratings after a completed deal (reviews.py, area 5: Trust & safety).

Uses the in-memory fake database, so the real Supabase is never touched.
Run them with:  pytest
"""

import pytest

import deals
import reviews
from fake_database import FakeDatabase
from listings import ListingError, NotAllowed

SELLER = "seller@novasbe.pt"
BUYER = "buyer@novasbe.pt"
OTHER = "other@novasbe.pt"


@pytest.fixture
def db():
    db = FakeDatabase()
    db.add_profile(SELLER, "Seller")
    db.add_profile(BUYER, "Buyer")
    db.add_profile(OTHER, "Other")
    return db


def a_deal(db, complete=True) -> int:
    listing = db.add_listing(db.get_profile(SELLER)["id"])
    request = deals.request_to_buy(db, listing["id"], BUYER)
    deals.accept_request(db, request["id"], SELLER)
    if complete:
        deals.confirm_sold(db, request["id"], SELLER)
        deals.confirm_received(db, request["id"], BUYER)
    return request["id"]


def pid(db, email) -> int:
    return db.get_profile(email)["id"]


def test_buyer_and_seller_rate_each_other(db):
    rid = a_deal(db)
    reviews.leave_review(db, rid, BUYER, 5, "Great seller, very quick!")
    reviews.leave_review(db, rid, SELLER, 2)
    assert reviews.summary(db, pid(db, SELLER)) == {"average": 5.0, "count": 1, "sold": 1}
    assert reviews.summary(db, pid(db, BUYER)) == {"average": 2.0, "count": 1, "sold": 0}


def test_only_completed_deals_can_be_rated(db):
    rid = a_deal(db, complete=False)
    with pytest.raises(ListingError):
        reviews.leave_review(db, rid, BUYER, 5)
    assert db.reviews == []


def test_a_deal_is_rated_once_per_person(db):
    rid = a_deal(db)
    reviews.leave_review(db, rid, BUYER, 4, "Fine")
    with pytest.raises(ListingError):
        reviews.leave_review(db, rid, BUYER, 1)
    assert reviews.reviewed_deals(db, BUYER) == {rid: {"stars": 4, "comment": "Fine"}}


def test_strangers_cannot_rate(db):
    rid = a_deal(db)
    with pytest.raises(NotAllowed):
        reviews.leave_review(db, rid, OTHER, 1)


def test_a_rating_survives_when_the_listing_is_deleted(db):
    rid = a_deal(db)
    reviews.leave_review(db, rid, BUYER, 1)
    listing_id = db.get_request(rid)["listing_id"]
    db.delete_listing(listing_id, pid(db, SELLER))
    assert reviews.summary(db, pid(db, SELLER))["average"] == 1.0


@pytest.mark.parametrize("stars", [0, 6, -1, 3.5, "5", True, None])
def test_stars_must_be_a_whole_number_from_1_to_5(db, stars):
    rid = a_deal(db)
    with pytest.raises(ListingError):
        reviews.leave_review(db, rid, BUYER, stars)
    assert db.reviews == []


def test_feedback_is_optional_and_trimmed(db):
    rid = a_deal(db)
    reviews.leave_review(db, rid, BUYER, 3, "   ")
    assert db.reviews[0]["comment"] is None
    rid2 = a_deal(db)
    reviews.leave_review(db, rid2, BUYER, 4, "  Nice kettle  ")
    assert db.reviews[1]["comment"] == "Nice kettle"


def test_feedback_has_a_length_limit(db):
    rid = a_deal(db)
    with pytest.raises(ListingError):
        reviews.leave_review(db, rid, BUYER, 5, "x" * (reviews.MAX_COMMENT_LENGTH + 1))
    reviews.leave_review(db, rid, BUYER, 5, "x" * reviews.MAX_COMMENT_LENGTH)


def test_average_is_rounded_to_one_decimal(db):
    for stars in (5, 4, 4):
        reviews.leave_review(db, a_deal(db), BUYER, stars)
    assert reviews.summary(db, pid(db, SELLER)) == {"average": 4.3, "count": 3, "sold": 3}


def test_no_ratings_means_no_average(db):
    assert reviews.summary(db, pid(db, SELLER)) == {"average": None, "count": 0, "sold": 0}


def test_older_thumbs_ratings_count_as_5_or_1_stars(db):
    seller = pid(db, SELLER)
    db.insert_review({"request_id": None, "reviewer_id": pid(db, BUYER),
                      "reviewee_id": seller, "positive": True})
    db.insert_review({"request_id": None, "reviewer_id": pid(db, OTHER),
                      "reviewee_id": seller, "positive": False})
    assert reviews.summary(db, seller)["average"] == 3.0


def test_recent_feedback_shows_written_feedback_newest_first(db):
    reviews.leave_review(db, a_deal(db), BUYER, 5, "First")
    reviews.leave_review(db, a_deal(db), BUYER, 3)  # no feedback: not listed
    reviews.leave_review(db, a_deal(db), BUYER, 4, "Third")
    shown = reviews.recent_feedback(db, pid(db, SELLER))
    assert [(f["stars"], f["comment"], f["reviewer_name"]) for f in shown] == [
        (4, "Third", "Buyer"), (5, "First", "Buyer")]


def test_star_text():
    assert reviews.star_text(4) == "★★★★☆"
    assert reviews.star_text(1) == "★☆☆☆☆"
