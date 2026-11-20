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
    reviews.leave_review(db, rid, BUYER, True)
    reviews.leave_review(db, rid, SELLER, False)
    assert reviews.summary(db, pid(db, SELLER)) == {"positive": 1, "negative": 0, "sold": 1}
    assert reviews.summary(db, pid(db, BUYER)) == {"positive": 0, "negative": 1, "sold": 0}


def test_only_completed_deals_can_be_rated(db):
    rid = a_deal(db, complete=False)
    with pytest.raises(ListingError):
        reviews.leave_review(db, rid, BUYER, True)
    assert db.reviews == []


def test_a_deal_is_rated_once_per_person(db):
    rid = a_deal(db)
    reviews.leave_review(db, rid, BUYER, True)
    with pytest.raises(ListingError):
        reviews.leave_review(db, rid, BUYER, False)
    assert reviews.reviewed_deals(db, BUYER) == {rid: True}


def test_strangers_cannot_rate(db):
    rid = a_deal(db)
    with pytest.raises(NotAllowed):
        reviews.leave_review(db, rid, OTHER, False)


def test_a_rating_survives_when_the_listing_is_deleted(db):
    rid = a_deal(db)
    reviews.leave_review(db, rid, BUYER, False)
    listing_id = db.get_request(rid)["listing_id"]
    db.delete_listing(listing_id, pid(db, SELLER))
    assert reviews.summary(db, pid(db, SELLER))["negative"] == 1
