"""Tests for the buying flow (deals.py): request -> accept -> both confirm -> sold,
plus decline, cancel, and the permission checks. Uses the in-memory fake database,
so the real Supabase is never touched.  Run them with:  pytest
"""

import pytest

import deals
from deals import ACCEPTED, CANCELLED, COMPLETED, DECLINED, REQUESTED
from fake_database import FakeDatabase
from listings import ACTIVE, RESERVED, SOLD, ListingError, NotAllowed, NotFound

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


def a_listing(db):
    seller_id = db.get_profile(SELLER)["id"]
    return db.add_listing(seller_id, "Desk lamp")


# --- request ------------------------------------------------------------------
def test_request_to_buy_creates_a_request(db):
    lid = a_listing(db)["id"]
    req = deals.request_to_buy(db, lid, BUYER)
    assert req["status"] == REQUESTED
    assert req["seller_confirmed_at"] is None and req["buyer_confirmed_at"] is None


def test_cannot_buy_your_own_listing(db):
    lid = a_listing(db)["id"]
    with pytest.raises(NotAllowed):
        deals.request_to_buy(db, lid, SELLER)


def test_cannot_request_twice(db):
    lid = a_listing(db)["id"]
    deals.request_to_buy(db, lid, BUYER)
    with pytest.raises(ListingError):
        deals.request_to_buy(db, lid, BUYER)


def test_request_on_missing_listing_is_not_found(db):
    with pytest.raises(NotFound):
        deals.request_to_buy(db, 999, BUYER)


# --- accept -------------------------------------------------------------------
def test_accept_reserves_the_listing_and_declines_others(db):
    listing = a_listing(db)
    lid = listing["id"]
    mine = deals.request_to_buy(db, lid, BUYER)
    other = deals.request_to_buy(db, lid, OTHER)
    deals.accept_request(db, mine["id"], SELLER)

    assert db.get_listing(lid)["status"] == RESERVED
    assert db.get_request(mine["id"])["status"] == ACCEPTED
    assert db.get_request(other["id"])["status"] == DECLINED


def test_only_the_seller_can_accept(db):
    lid = a_listing(db)["id"]
    req = deals.request_to_buy(db, lid, BUYER)
    with pytest.raises(NotAllowed):
        deals.accept_request(db, req["id"], OTHER)


# --- the two confirmations ----------------------------------------------------
def _accepted_deal(db):
    listing = a_listing(db)
    req = deals.request_to_buy(db, listing["id"], BUYER)
    deals.accept_request(db, req["id"], SELLER)
    return listing["id"], req["id"]


def test_one_confirmation_alone_does_not_sell(db):
    lid, rid = _accepted_deal(db)
    deals.confirm_sold(db, rid, SELLER)           # seller only
    assert db.get_listing(lid)["status"] == RESERVED
    assert db.get_request(rid)["status"] == ACCEPTED


def test_both_confirmations_mark_it_sold_seller_first(db):
    lid, rid = _accepted_deal(db)
    deals.confirm_sold(db, rid, SELLER)
    deals.confirm_received(db, rid, BUYER)
    assert db.get_listing(lid)["status"] == SOLD
    assert db.get_request(rid)["status"] == COMPLETED


def test_the_buyer_confirming_alone_marks_it_sold(db):
    lid, rid = _accepted_deal(db)
    deals.confirm_received(db, rid, BUYER)        # the seller doesn't need to confirm
    assert db.get_listing(lid)["status"] == SOLD
    assert db.get_request(rid)["status"] == COMPLETED
    with pytest.raises(ListingError):             # nothing left for the seller to do
        deals.confirm_sold(db, rid, SELLER)


def test_the_seller_saying_handed_over_does_not_finish_the_deal(db):
    lid, rid = _accepted_deal(db)
    deals.confirm_sold(db, rid, SELLER)
    assert db.get_request(rid)["status"] == ACCEPTED
    assert db.get_listing(lid)["status"] == RESERVED


def test_only_the_buyer_can_confirm_received(db):
    lid, rid = _accepted_deal(db)
    with pytest.raises(NotAllowed):
        deals.confirm_received(db, rid, OTHER)


def test_cannot_confirm_before_acceptance(db):
    lid = a_listing(db)["id"]
    req = deals.request_to_buy(db, lid, BUYER)
    with pytest.raises(ListingError):
        deals.confirm_received(db, req["id"], BUYER)
    with pytest.raises(ListingError):
        deals.confirm_sold(db, req["id"], SELLER)


# --- decline / cancel ---------------------------------------------------------
def test_decline_a_pending_request(db):
    lid = a_listing(db)["id"]
    req = deals.request_to_buy(db, lid, BUYER)
    deals.decline_request(db, req["id"], SELLER)
    assert db.get_request(req["id"])["status"] == DECLINED
    assert db.get_listing(lid)["status"] == ACTIVE


def test_cancel_an_accepted_deal_frees_the_listing(db):
    lid, rid = _accepted_deal(db)
    deals.cancel_deal(db, rid, BUYER)             # buyer backs out
    assert db.get_request(rid)["status"] == CANCELLED
    assert db.get_listing(lid)["status"] == ACTIVE


def test_seller_can_also_cancel(db):
    lid, rid = _accepted_deal(db)
    deals.cancel_deal(db, rid, SELLER)
    assert db.get_listing(lid)["status"] == ACTIVE


def test_a_stranger_cannot_cancel(db):
    lid, rid = _accepted_deal(db)
    with pytest.raises(NotAllowed):
        deals.cancel_deal(db, rid, OTHER)


def test_cannot_cancel_a_completed_deal(db):
    lid, rid = _accepted_deal(db)
    deals.confirm_sold(db, rid, SELLER)
    deals.confirm_received(db, rid, BUYER)
    with pytest.raises(ListingError):
        deals.cancel_deal(db, rid, BUYER)


def test_after_cancel_the_buyer_can_request_again(db):
    lid, rid = _accepted_deal(db)
    deals.cancel_deal(db, rid, BUYER)
    again = deals.request_to_buy(db, lid, BUYER)   # no longer a "live" request blocking it
    assert again["status"] == REQUESTED


# --- views' helpers -----------------------------------------------------------
def test_requests_on_listing_shows_the_buyer_name(db):
    lid = a_listing(db)["id"]
    deals.request_to_buy(db, lid, BUYER)
    rows = deals.requests_on_listing(db, lid, SELLER)
    assert rows[0]["buyer_name"] == "Buyer"


def test_my_purchases_attaches_the_listing(db):
    lid = a_listing(db)["id"]
    deals.request_to_buy(db, lid, BUYER)
    mine = deals.my_purchases(db, BUYER)
    assert len(mine) == 1
    assert mine[0]["listing"]["id"] == lid


# --- two clicks at the same moment -------------------------------------------
def test_accept_fails_if_the_buyer_cancelled_meanwhile(db):
    lid = a_listing(db)["id"]
    req = deals.request_to_buy(db, lid, BUYER)
    seen_by_seller = db.get_request(req["id"])           # the seller's page loaded...
    db.requests[req["id"]]["status"] = CANCELLED         # ...then the buyer cancelled
    real_get = db.get_request
    db.get_request = lambda rid: seen_by_seller if rid == req["id"] else real_get(rid)
    with pytest.raises(ListingError):
        deals.accept_request(db, req["id"], SELLER)
    assert db.get_listing(lid)["status"] == ACTIVE        # the listing was given back
    assert db.requests[req["id"]]["status"] == CANCELLED


def test_two_buyers_can_never_both_be_accepted(db):
    lid = a_listing(db)["id"]
    first = deals.request_to_buy(db, lid, BUYER)
    second = deals.request_to_buy(db, lid, OTHER)
    deals.accept_request(db, first["id"], SELLER)
    with pytest.raises(ListingError):
        deals.accept_request(db, second["id"], SELLER)
    accepted = [r for r in db.requests.values() if r["status"] == ACCEPTED]
    assert [r["id"] for r in accepted] == [first["id"]]


def test_a_reserved_item_cannot_be_requested(db):
    lid, rid = _accepted_deal(db)
    with pytest.raises(ListingError):
        deals.request_to_buy(db, lid, OTHER)


def test_a_blocked_student_cannot_request(db):
    lid = a_listing(db)["id"]
    db.get_profile(BUYER)["blocked_at"] = "now"
    with pytest.raises(NotAllowed):
        deals.request_to_buy(db, lid, BUYER)


# --- the counts in the menu ---------------------------------------------------
def test_to_do_counts_what_each_side_must_do(db):
    lid = a_listing(db)["id"]
    req = deals.request_to_buy(db, lid, BUYER)
    assert deals.to_do(db, SELLER)["sales"] == 1          # answer the buyer
    assert deals.to_do(db, BUYER)["purchases"] == 0       # nothing to do yet

    deals.accept_request(db, req["id"], SELLER)
    assert deals.to_do(db, SELLER)["sales"] == 0
    assert deals.to_do(db, BUYER)["purchases"] == 1       # meet + confirm

    deals.confirm_received(db, req["id"], BUYER)
    assert deals.to_do(db, BUYER)["purchases"] == 0
    assert deals.to_do(db, SELLER)["sales"] == 0          # done: nothing for the seller


# --- history ------------------------------------------------------------------
def test_declined_requests_stay_visible_to_the_buyer(db):
    lid = a_listing(db)["id"]
    req = deals.request_to_buy(db, lid, BUYER)
    deals.decline_request(db, req["id"], SELLER)
    assert [d["status"] for d in deals.my_purchases(db, BUYER)] == [DECLINED]


def test_my_sales_lists_completed_sales_with_the_buyer(db):
    lid, rid = _accepted_deal(db)
    deals.confirm_sold(db, rid, SELLER)
    deals.confirm_received(db, rid, BUYER)
    sales = deals.my_sales(db, SELLER)
    assert [(s["id"], s["title"], s["buyer_name"]) for s in sales] == [(rid, "Desk lamp", "Buyer")]


# --- blocking -----------------------------------------------------------------
def test_blocking_a_buyer_frees_the_item_reserved_for_them(db):
    lid, rid = _accepted_deal(db)
    deals.cancel_deals_of(db, db.get_profile(BUYER)["id"])
    assert db.get_request(rid)["status"] == CANCELLED
    assert db.get_listing(lid)["status"] == ACTIVE


def test_blocking_a_seller_cancels_requests_for_their_items(db):
    lid = a_listing(db)["id"]
    waiting = deals.request_to_buy(db, lid, OTHER)
    deals.cancel_deals_of(db, db.get_profile(SELLER)["id"])
    assert db.get_request(waiting["id"])["status"] == CANCELLED
