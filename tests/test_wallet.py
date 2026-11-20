"""Tests for the wallet (Nova credits): adding credits, and money moving with a deal.

Uses the in-memory fake database (tests/fake_database.py), like the other tests.
Run them with:  pytest
"""

from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from PIL import Image

import admin
import deals
import listings
import wallet
from fake_database import FakeDatabase
from listings import ListingError, NotAllowed

SELLER, BUYER, OTHER = "seller@novasbe.pt", "buyer@novasbe.pt", "other@novasbe.pt"


def photo() -> bytes:
    out = BytesIO()
    Image.new("RGB", (20, 20), (200, 50, 50)).save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture
def db():
    db = FakeDatabase()
    for email in (SELLER, BUYER, OTHER):
        db.add_profile(email)
    return db


def pid(db, email):
    return db.get_profile(email)["id"]


def sell(db, price_cents=2000, title="Desk lamp"):
    return listings.create_listing(
        db, SELLER, title=title, description="A lamp in good condition.", free=price_cents == 0,
        price_cents=price_cents or None, category="Furniture", condition="Good",
        pickup_area="Carcavelos", photos=[photo()])


def bal(db, email):
    return wallet.my_balance(db, email)


def deal(db, listing_id, buyer=BUYER):
    """Buyer asks, seller accepts. Returns the request id."""
    request = deals.request_to_buy(db, listing_id, buyer)
    deals.accept_request(db, request["id"], SELLER)
    return request["id"]


# --- adding credits -------------------------------------------------------------

def test_new_students_start_with_zero(db):
    assert bal(db, BUYER) == 0


@pytest.mark.parametrize("amount", wallet.TOP_UP_AMOUNTS)
def test_add_credits_with_the_buttons(db, amount):
    wallet.add_credits(db, BUYER, amount)
    assert bal(db, BUYER) == amount


@pytest.mark.parametrize("amount", [0, -1000, 999, 123_456])
def test_other_amounts_are_refused(db, amount):
    with pytest.raises(wallet.WalletError):
        wallet.add_credits(db, BUYER, amount)
    assert bal(db, BUYER) == 0


def test_balance_has_a_maximum(db):
    for _ in range(wallet.MAX_BALANCE_CENTS // 10_000):
        wallet.add_credits(db, BUYER, 10_000)
    assert bal(db, BUYER) == wallet.MAX_BALANCE_CENTS
    with pytest.raises(wallet.WalletError, match="at most"):
        wallet.add_credits(db, BUYER, 1_000)


def test_only_nova_students_with_a_profile_have_a_balance(db):
    with pytest.raises(NotAllowed):
        wallet.add_credits(db, "someone@gmail.com", 1_000)
    with pytest.raises(NotAllowed):
        wallet.add_credits(db, "noprofile@novasbe.pt", 1_000)


# --- asking and accepting -------------------------------------------------------

def test_asking_to_buy_needs_enough_credits(db):
    listing_id = sell(db, 2000)
    with pytest.raises(ListingError, match="You need €20.00 in credits"):
        deals.request_to_buy(db, listing_id, BUYER)
    wallet.add_credits(db, BUYER, 5_000)
    deals.request_to_buy(db, listing_id, BUYER)
    assert bal(db, BUYER) == 5_000  # asking takes nothing


def test_accepting_holds_the_price_from_the_buyer(db):
    wallet.add_credits(db, BUYER, 5_000)
    deal(db, sell(db, 2000))
    assert bal(db, BUYER) == 3_000
    assert bal(db, SELLER) == 0  # not yet: the buyer must confirm first


def test_accept_fails_if_the_buyer_spent_the_credits_meanwhile(db):
    wallet.add_credits(db, BUYER, 5_000)
    lamp, chair = sell(db, 3000, "Lamp"), sell(db, 3000, "Chair")
    first = deals.request_to_buy(db, lamp, BUYER)
    second = deals.request_to_buy(db, chair, BUYER)
    deals.accept_request(db, first["id"], SELLER)  # €30 held, €20 left
    with pytest.raises(ListingError, match="doesn't have enough credits"):
        deals.accept_request(db, second["id"], SELLER)
    # Nothing changed for the second item: still active, request still waiting.
    assert listings.get_listing(db, chair)["status"] == listings.ACTIVE
    assert db.get_request(second["id"])["status"] == deals.REQUESTED
    assert bal(db, BUYER) == 2_000


def test_free_items_never_touch_the_wallet(db):
    request_id = deal(db, sell(db, 0))
    deals.confirm_received(db, request_id, BUYER)
    deals.confirm_sold(db, request_id, SELLER)
    assert bal(db, BUYER) == 0 and bal(db, SELLER) == 0
    assert db.wallet == []


# --- the buyer confirms: money to the seller -----------------------------------

def test_buyer_confirming_pays_the_seller(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    deals.confirm_received(db, request_id, BUYER)
    assert bal(db, SELLER) == 2_000
    assert bal(db, BUYER) == 3_000
    deals.confirm_sold(db, request_id, SELLER)
    assert db.get_request(request_id)["status"] == deals.COMPLETED
    assert bal(db, SELLER) == 2_000  # paid once, not again on completion


def test_seller_confirming_first_does_not_pay_yet(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    deals.confirm_sold(db, request_id, SELLER)
    assert bal(db, SELLER) == 0
    deals.confirm_received(db, request_id, BUYER)
    assert bal(db, SELLER) == 2_000


def test_paid_price_is_the_price_when_accepted(db):
    wallet.add_credits(db, BUYER, 5_000)
    listing_id = sell(db, 2000)
    request_id = deal(db, listing_id)
    db.listings[listing_id]["price_cents"] = 4500  # changed after accepting
    deals.confirm_received(db, request_id, BUYER)
    assert bal(db, SELLER) == 2_000


# --- called off: money back to the buyer ----------------------------------------

@pytest.mark.parametrize("who", [BUYER, SELLER])
def test_cancelling_an_accepted_deal_refunds_the_buyer(db, who):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    deals.cancel_deal(db, request_id, who)
    assert bal(db, BUYER) == 5_000 and bal(db, SELLER) == 0


def test_declining_an_accepted_buyer_refunds_them(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    deals.decline_request(db, request_id, SELLER)
    assert bal(db, BUYER) == 5_000


def test_after_the_buyer_confirmed_the_deal_cannot_be_called_off(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    deals.confirm_received(db, request_id, BUYER)
    for call_off in (lambda: deals.cancel_deal(db, request_id, SELLER),
                     lambda: deals.cancel_deal(db, request_id, BUYER),
                     lambda: deals.decline_request(db, request_id, SELLER)):
        with pytest.raises(ListingError, match="already confirmed"):
            call_off()
    assert bal(db, SELLER) == 2_000 and bal(db, BUYER) == 3_000


def test_money_is_never_paid_and_refunded_both(db):
    wallet.add_credits(db, BUYER, 5_000)
    request = db.get_request(deal(db, sell(db, 2000)))
    listing = db.get_listing(request["listing_id"])
    wallet.release(db, request, listing)
    wallet.refund(db, request)           # refused: already released
    wallet.release(db, request, listing)  # refused: no second payment
    assert bal(db, SELLER) == 2_000 and bal(db, BUYER) == 3_000


def test_a_double_click_on_accept_holds_only_once(db):
    wallet.add_credits(db, BUYER, 5_000)
    request = db.get_request(deal(db, sell(db, 2000)))
    listing = db.get_listing(request["listing_id"])
    assert wallet.hold(db, request, listing)  # second hold of the same deal
    assert bal(db, BUYER) == 3_000


def test_admin_removing_a_listing_refunds_the_buyer(db, monkeypatch):
    import reports
    monkeypatch.setattr(admin, "admin_emails", lambda: [OTHER])  # OTHER is the admin here
    wallet.add_credits(db, BUYER, 5_000)
    listing_id = sell(db, 2000)
    deal(db, listing_id)
    report_id = reports.create_report(db, BUYER, listing_id=listing_id,
                                      reason=reports.REASONS[0], details="")
    admin.remove_listing(db, OTHER, report_id)
    assert db.get_listing(listing_id) is None
    assert bal(db, BUYER) == 5_000


def test_blocking_a_seller_refunds_their_buyers(db):
    wallet.add_credits(db, BUYER, 5_000)
    deal(db, sell(db, 2000))
    deals.cancel_deals_of(db, pid(db, SELLER))
    assert bal(db, BUYER) == 5_000


# --- history --------------------------------------------------------------------

def test_history_tells_the_whole_story_newest_first(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000, "Desk lamp"))
    deals.confirm_received(db, request_id, BUYER)
    buyer_lines = [(e["amount_cents"], e["text"]) for e in wallet.my_history(db, BUYER)]
    assert buyer_lines == [
        (-2000, "Paid for “Desk lamp” (held until you confirm you got it)"),
        (5000, "Added credits"),
    ]
    assert [(e["amount_cents"], e["text"]) for e in wallet.my_history(db, SELLER)] == \
        [(2000, "Sold “Desk lamp”")]


def test_money_is_never_created_or_lost(db):
    wallet.add_credits(db, BUYER, 10_000)
    wallet.add_credits(db, OTHER, 10_000)
    a, b, c = sell(db, 1500, "Lamp"), sell(db, 2500, "Chair"), sell(db, 4000, "Desk")
    deals.confirm_received(db, deal(db, a), BUYER)
    deals.cancel_deal(db, deal(db, b, OTHER), OTHER)
    deal(db, c, OTHER)  # still held
    total = sum(bal(db, who) for who in (SELLER, BUYER, OTHER))
    held = 4000
    assert total + held == 20_000


# --- 48 hours after the hand-over: the seller is paid automatically -------------

def handed_over_hours_ago(db, request_id, hours):
    """The seller confirmed the hand-over `hours` ago."""
    deals.confirm_sold(db, request_id, SELLER)
    moment = datetime.now(timezone.utc) - timedelta(hours=hours)
    db.requests[request_id]["seller_confirmed_at"] = moment.isoformat()


def test_no_countdown_before_the_seller_confirms_the_hand_over(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    assert deals.payment_due(db.get_request(request_id)) is None
    later = datetime.now(timezone.utc) + timedelta(days=30)
    assert deals.release_overdue(db, BUYER, now=later) == 0
    assert bal(db, SELLER) == 0


def test_the_buyer_has_48_hours_after_the_hand_over(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    handed_over_hours_ago(db, request_id, 47)
    due = deals.payment_due(db.get_request(request_id))
    assert timedelta(minutes=59) < due - datetime.now(timezone.utc) <= timedelta(hours=1)
    assert deals.release_overdue(db, SELLER) == 0
    assert bal(db, SELLER) == 0


@pytest.mark.parametrize("who_opens_the_app", [SELLER, BUYER])
def test_after_48_hours_the_seller_is_paid_automatically(db, who_opens_the_app):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    handed_over_hours_ago(db, request_id, 49)
    deals.to_do(db, who_opens_the_app)  # what every page does when it opens
    assert bal(db, SELLER) == 2_000 and bal(db, BUYER) == 3_000
    assert db.get_request(request_id)["status"] == deals.COMPLETED
    assert listings.get_listing(db, db.get_request(request_id)["listing_id"])["status"] == \
        listings.SOLD


def test_automatic_payment_happens_only_once(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    handed_over_hours_ago(db, request_id, 72)
    deals.release_overdue(db, SELLER)
    deals.release_overdue(db, BUYER)
    deals.release_overdue(db, SELLER)
    assert bal(db, SELLER) == 2_000


def test_buyer_confirming_in_time_stops_the_countdown(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    handed_over_hours_ago(db, request_id, 10)
    deals.confirm_received(db, request_id, BUYER)
    assert deals.payment_due(db.get_request(request_id)) is None
    later = datetime.now(timezone.utc) + timedelta(days=5)
    deals.release_overdue(db, SELLER, now=later)
    assert bal(db, SELLER) == 2_000  # paid once, when the buyer confirmed


def test_a_cancelled_deal_is_never_paid_automatically(db):
    wallet.add_credits(db, BUYER, 5_000)
    request_id = deal(db, sell(db, 2000))
    deals.confirm_sold(db, request_id, SELLER)
    deals.cancel_deal(db, request_id, BUYER)  # the buyer reported a problem in time
    later = datetime.now(timezone.utc) + timedelta(days=5)
    deals.release_overdue(db, SELLER, now=later)
    assert bal(db, SELLER) == 0 and bal(db, BUYER) == 5_000
