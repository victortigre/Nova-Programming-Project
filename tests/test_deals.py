"""Tests for buying by bank transfer (deals.py): Buy Now in a chat -> the buyer
pays and says so -> the seller confirms -> sold. Plus the 15 minutes to pay,
"not received yet", cancelling and the permission checks.

Uses the in-memory fake database, so the real Supabase is never touched.
Run them with:  pytest
"""

from datetime import datetime, timedelta, timezone

import pytest

import deals
from deal_helpers import finish_purchase, give_bank_details, start_purchase
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


def pid(db, email):
    return db.get_profile(email)["id"]


def a_listing(db):
    return db.add_listing(pid(db, SELLER), "Desk lamp")["id"]


def a_chat(db, listing_id, buyer=BUYER, offer_status="accepted", amount=1500, chat_id="c1"):
    db.add_chat(chat_id, listing_id, pid(db, buyer), pid(db, SELLER))
    db.add_offer(chat_id, pid(db, buyer), amount, status=offer_status)
    return chat_id


# --- 1. Buy Now --------------------------------------------------------------------

def test_buy_now_reserves_at_the_agreed_price_with_15_minutes_to_pay(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    deal = deals.buy_now(db, BUYER, a_chat(db, lid, amount=1500))
    assert deal["status"] == ACCEPTED and deal["agreed_price_cents"] == 1500
    assert db.get_listing(lid)["status"] == RESERVED
    due = deals.pay_due(deal)
    expected = datetime.now(timezone.utc) + timedelta(minutes=15)
    assert abs((due - expected).total_seconds()) < 60


def test_buy_now_needs_an_accepted_offer(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    for status in ("pending", "declined"):
        chat = a_chat(db, lid, offer_status=status, chat_id=f"c-{status}")
        with pytest.raises(ListingError, match="Agree a price"):
            deals.buy_now(db, BUYER, chat)
    assert db.get_listing(lid)["status"] == ACTIVE


def test_buy_now_needs_the_sellers_bank_details(db):
    lid = a_listing(db)
    with pytest.raises(ListingError, match="way to get paid"):
        deals.buy_now(db, BUYER, a_chat(db, lid))
    assert db.get_listing(lid)["status"] == ACTIVE


def test_only_the_buyer_of_the_chat_can_buy_now(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    chat = a_chat(db, lid)
    for who in (SELLER, OTHER):
        with pytest.raises(NotAllowed):
            deals.buy_now(db, who, chat)


def test_a_reserved_or_sold_item_cannot_be_bought(db):
    lid = a_listing(db)
    start_purchase(db, lid, BUYER)
    with pytest.raises(ListingError, match="reserved"):
        deals.buy_now(db, OTHER, a_chat(db, lid, buyer=OTHER, chat_id="c2"))
    db.listings[lid]["status"] = SOLD
    with pytest.raises(ListingError, match="sold"):
        deals.buy_now(db, OTHER, a_chat(db, lid, buyer=OTHER, chat_id="c3"))


def test_buy_now_twice_starts_one_deal(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    chat = a_chat(db, lid)
    deals.buy_now(db, BUYER, chat)
    with pytest.raises(ListingError):
        deals.buy_now(db, BUYER, chat)
    assert len(db.requests) == 1


def test_an_item_past_its_available_until_date_cannot_be_bought(db):
    from datetime import date, timedelta
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    db.listings[lid]["available_until"] = (date.today() - timedelta(days=1)).isoformat()
    with pytest.raises(ListingError, match="available until"):
        deals.buy_now(db, BUYER, a_chat(db, lid))
    assert db.listings[lid]["status"] == "active"

# --- Buy Now from the item page (the listed price, no offer) ------------------------

def a_plain_chat(db, listing_id, chat_id="plain"):
    db.add_chat(chat_id, listing_id, pid(db, BUYER), pid(db, SELLER))
    return chat_id


def test_buy_at_the_listed_price_without_an_offer(db):
    lid = a_listing(db)
    db.listings[lid]["price_cents"] = 1600
    give_bank_details(db, SELLER)
    deal = deals.buy_at_listed_price(db, BUYER, a_plain_chat(db, lid))
    assert deal["agreed_price_cents"] == 1600 and deal["status"] == ACCEPTED
    assert db.get_listing(lid)["status"] == RESERVED
    assert deals.deal_in_chat(db, SELLER, "plain")["id"] == deal["id"]


def test_free_items_cannot_be_bought_there_is_nothing_to_pay(db):
    lid = a_listing(db)
    db.listings[lid]["price_cents"] = 0
    give_bank_details(db, SELLER)
    with pytest.raises(ListingError, match="free"):
        deals.buy_at_listed_price(db, BUYER, a_plain_chat(db, lid))
    assert db.get_listing(lid)["status"] == ACTIVE


def test_buying_at_the_listed_price_has_the_same_checks(db):
    lid = a_listing(db)
    db.listings[lid]["price_cents"] = 1600
    chat = a_plain_chat(db, lid)
    with pytest.raises(ListingError, match="way to get paid"):
        deals.buy_at_listed_price(db, BUYER, chat)
    give_bank_details(db, SELLER)
    with pytest.raises(NotAllowed):
        deals.buy_at_listed_price(db, SELLER, chat)
    deals.buy_at_listed_price(db, BUYER, chat)
    with pytest.raises(ListingError):
        deals.buy_at_listed_price(db, BUYER, chat)  # only once


# --- where to pay ----------------------------------------------------------------------

def test_the_buyer_sees_the_sellers_bank_details(db):
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER, price_cents=4500)
    details = deals.payment_details(db, deal["id"], BUYER)
    assert [m["key"] for m in details["methods"]] == ["bank"]
    assert details["methods"][0]["details"] == [
        ("Account holder", "Test Seller"), ("IBAN", "PT50 0002 0123 1234 5678 9015 4")]
    assert details["amount_cents"] == 4500
    assert details["reference"] == f"Nova Marketplace #{deal['id']}"


def test_nobody_else_sees_the_bank_details(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    with pytest.raises(NotAllowed):
        deals.payment_details(db, deal["id"], OTHER)


def test_the_deal_is_found_from_its_chat_by_both_sides_only(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    chat = a_chat(db, lid)
    assert deals.deal_in_chat(db, BUYER, chat) is None
    deal = deals.buy_now(db, BUYER, chat)
    assert deals.deal_in_chat(db, BUYER, chat)["id"] == deal["id"]
    assert deals.deal_in_chat(db, SELLER, chat)["id"] == deal["id"]
    assert deals.deal_in_chat(db, OTHER, chat) is None


# --- 2 + 3. pay, then the seller confirms ------------------------------------------------

def test_paid_and_confirmed_marks_it_sold(db):
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER)
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    assert db.get_request(deal["id"])["status"] == ACCEPTED  # not yet: the seller checks
    deals.confirm_payment(db, deal["id"], SELLER)
    assert db.get_request(deal["id"])["status"] == COMPLETED
    assert db.get_listing(lid)["status"] == SOLD


def test_saying_you_paid_posts_a_chat_message_so_the_sellers_inbox_lights_up(db):
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER)
    assert db.messages == []  # the chat is empty until the buyer acts
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    assert len(db.messages) == 1  # a line now sits in the chat → the Inbox can show it unread
    note = db.messages[0]
    assert note["conversation_id"] == deal["conversation_id"]
    assert note["sender_id"] == deal["buyer_id"]  # from the buyer, so it's unread for the seller
    assert "paid" in note["body"].lower() and "confirm" in note["body"].lower()


def test_the_seller_cannot_confirm_before_the_buyer_paid(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    with pytest.raises(ListingError, match="hasn't said they paid"):
        deals.confirm_payment(db, deal["id"], SELLER)


def test_only_the_buyer_says_paid_and_only_the_seller_confirms(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    for who in (SELLER, OTHER):
        with pytest.raises(NotAllowed):
            deals.mark_paid(db, deal["id"], who, "bank")
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    for who in (BUYER, OTHER):
        with pytest.raises(NotAllowed):
            deals.confirm_payment(db, deal["id"], who)
        with pytest.raises(NotAllowed):
            deals.payment_not_received(db, deal["id"], who)


def test_not_received_sends_it_back_to_the_buyer(db):
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER)
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    deals.payment_not_received(db, deal["id"], SELLER)
    fresh = db.get_request(deal["id"])
    assert fresh["paid_at"] is None and fresh["payment_missing_at"]
    assert fresh["status"] == ACCEPTED and db.get_listing(lid)["status"] == RESERVED
    deals.mark_paid(db, deal["id"], BUYER, "bank")  # the buyer checks and says it again
    deals.confirm_payment(db, deal["id"], SELLER)
    assert db.get_listing(lid)["status"] == SOLD


def test_saying_paid_twice_is_refused(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    with pytest.raises(ListingError, match="already said"):
        deals.mark_paid(db, deal["id"], BUYER, "bank")


# --- the 15 minutes to pay ----------------------------------------------------------------

def overdue(db, request_id, minutes_late=1):
    db.requests[request_id]["pay_by"] = (
        datetime.now(timezone.utc) - timedelta(minutes=minutes_late)).isoformat()


def test_unpaid_after_15_minutes_is_cancelled_and_back_on_sale(db):
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER)
    overdue(db, deal["id"])
    deals.to_do(db, SELLER)  # opening any page runs the check
    assert db.get_request(deal["id"])["status"] == CANCELLED
    assert db.get_listing(lid)["status"] == ACTIVE


def test_not_cancelled_before_the_15_minutes(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    later = datetime.now(timezone.utc) + timedelta(minutes=14)
    assert deals.cancel_overdue(db, BUYER, now=later) == 0
    assert db.get_request(deal["id"])["status"] == ACCEPTED


def test_once_the_buyer_said_paid_there_is_no_automatic_cancel(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    much_later = datetime.now(timezone.utc) + timedelta(days=30)
    assert deals.cancel_overdue(db, BUYER, now=much_later) == 0
    assert db.get_request(deal["id"])["status"] == ACCEPTED


def test_after_not_received_there_is_no_automatic_cancel(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    deals.payment_not_received(db, deal["id"], SELLER)
    overdue(db, deal["id"])
    assert deals.cancel_overdue(db, SELLER) == 0


def test_paying_after_the_15_minutes_is_refused(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    overdue(db, deal["id"])
    with pytest.raises(ListingError, match="15 minutes"):
        deals.mark_paid(db, deal["id"], BUYER, "bank")


# --- cancelling -------------------------------------------------------------------------

@pytest.mark.parametrize("who", [BUYER, SELLER])
def test_either_side_can_cancel_before_paying(db, who):
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER)
    deals.cancel_deal(db, deal["id"], who)
    assert db.get_request(deal["id"])["status"] == CANCELLED
    assert db.get_listing(lid)["status"] == ACTIVE


@pytest.mark.parametrize("who", [BUYER, SELLER])
def test_nobody_can_cancel_while_the_seller_checks_the_payment(db, who):
    deal = start_purchase(db, a_listing(db), BUYER)
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    with pytest.raises(ListingError, match="says they paid"):
        deals.cancel_deal(db, deal["id"], who)


def test_after_not_received_only_the_seller_can_cancel(db):
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER)
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    deals.payment_not_received(db, deal["id"], SELLER)
    with pytest.raises(ListingError, match="didn't arrive"):
        deals.cancel_deal(db, deal["id"], BUYER)
    deals.cancel_deal(db, deal["id"], SELLER)
    assert db.get_listing(lid)["status"] == ACTIVE


def test_strangers_cannot_cancel_and_finished_deals_stay_finished(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    with pytest.raises(NotAllowed):
        deals.cancel_deal(db, deal["id"], OTHER)
    finish_purchase(db, deal["id"], BUYER, SELLER)
    for who in (BUYER, SELLER):
        with pytest.raises(ListingError):
            deals.cancel_deal(db, deal["id"], who)


def test_missing_deal_is_not_found(db):
    with pytest.raises(NotFound):
        deals.mark_paid(db, 999, BUYER, "bank")
    with pytest.raises(NotFound):
        deals.cancel_deal(db, 999, BUYER)


# --- old "Request to buy" requests -------------------------------------------------------

def test_an_old_waiting_request_can_be_declined(db):
    lid = a_listing(db)
    old = db.insert_request({"listing_id": lid, "buyer_id": pid(db, BUYER)})
    assert old["status"] == REQUESTED
    with pytest.raises(NotAllowed):
        deals.decline_request(db, old["id"], OTHER)
    deals.decline_request(db, old["id"], SELLER)
    assert db.get_request(old["id"])["status"] == DECLINED


# --- lists and counts ---------------------------------------------------------------------

def test_to_do_counts_what_each_side_must_do(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    assert deals.to_do(db, BUYER)["purchases"] == 1     # pay
    assert deals.to_do(db, SELLER)["sales"] == 0        # nothing yet
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    assert deals.to_do(db, BUYER)["purchases"] == 0
    assert deals.to_do(db, SELLER)["check_payment"] == 1
    deals.confirm_payment(db, deal["id"], SELLER)
    assert deals.to_do(db, SELLER)["sales"] == 0


def test_my_sales_and_purchases_use_the_agreed_price(db):
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER, price_cents=3300)
    finish_purchase(db, deal["id"], BUYER, SELLER)
    sale = deals.my_sales(db, SELLER)[0]
    assert sale["price_cents"] == 3300 and sale["buyer_name"] == "Buyer"
    purchase = deals.my_purchases(db, BUYER)[0]
    assert deals.price_of(purchase) == 3300 and purchase["listing"]["id"] == lid


def test_blocked_students_cannot_buy(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    db.profiles[BUYER]["blocked_at"] = "now"
    with pytest.raises(NotAllowed, match="blocked"):
        deals.buy_now(db, BUYER, a_chat(db, lid))


# --- bank transfer or cash ---------------------------------------------------------------

def seller_accepts(db, **methods):
    db.save_payment_methods(SELLER, methods)


def test_a_cash_only_seller_can_be_bought_from(db):
    seller_accepts(db, accepts_cash=True)
    deal = start_purchase(db, a_listing(db), BUYER)
    details = deals.payment_details(db, deal["id"], BUYER)
    assert [m["key"] for m in details["methods"]] == ["cash"]


def test_buying_from_a_cash_only_seller_has_no_15_minute_deadline(db):
    seller_accepts(db, accepts_cash=True)  # no IBAN: cash is the only way
    deal = start_purchase(db, a_listing(db), BUYER)
    fresh = db.get_request(deal["id"])
    assert deals.paying_cash(fresh) and deals.pay_due(fresh) is None
    overdue(db, deal["id"], minutes_late=60)
    assert deals.cancel_overdue(db, BUYER) == 0
    assert deals.waiting_on_me(db, BUYER)["pay"][0]["cash"]


def test_the_buyer_can_only_say_they_paid_in_a_way_the_seller_accepts(db):
    seller_accepts(db, accepts_cash=True)  # no IBAN
    deal = start_purchase(db, a_listing(db), BUYER)
    for method in ("bank", "bitcoin"):
        with pytest.raises(ListingError, match="Choose how you paid"):
            deals.mark_paid(db, deal["id"], BUYER, method)
    deals.mark_paid(db, deal["id"], BUYER, "cash")  # e.g. paid when they met
    assert db.get_request(deal["id"])["payment_method"] == "cash"


def test_cash_has_no_deadline_and_the_seller_confirms_when_they_meet(db):
    seller_accepts(db, accepts_cash=True)
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER)
    deals.choose_cash(db, deal["id"], BUYER)
    fresh = db.get_request(deal["id"])
    assert deals.paying_cash(fresh) and deals.pay_due(fresh) is None
    overdue(db, deal["id"], minutes_late=12000)
    assert deals.cancel_overdue(db, BUYER) == 0  # no automatic cancel for cash
    assert deals.to_do(db, SELLER)["check_payment"] == 1
    deals.confirm_payment(db, deal["id"], SELLER)  # cash received
    assert db.get_listing(lid)["status"] == SOLD


def test_bank_transfer_keeps_the_15_minutes(db):
    seller_accepts(db, bank_holder="Test Seller", iban="PT50000201231234567890154",
                   accepts_cash=True)
    deal = start_purchase(db, a_listing(db), BUYER)
    assert deals.pay_due(db.get_request(deal["id"])) is not None
    overdue(db, deal["id"])
    assert deals.cancel_overdue(db, BUYER) == 1


def test_cash_only_if_the_seller_accepts_it(db):
    deal = start_purchase(db, a_listing(db), BUYER)  # bank transfer only
    with pytest.raises(ListingError, match="doesn't accept cash"):
        deals.choose_cash(db, deal["id"], BUYER)


def test_either_side_can_cancel_a_cash_deal_before_they_meet(db):
    seller_accepts(db, accepts_cash=True)
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER)
    deals.choose_cash(db, deal["id"], BUYER)
    deals.cancel_deal(db, deal["id"], SELLER)
    assert db.get_listing(lid)["status"] == ACTIVE


# --- the notifications on Browse, with names ----------------------------------------------

def test_waiting_on_me_names_the_other_student(db):
    lid = a_listing(db)
    deal = start_purchase(db, lid, BUYER, price_cents=2000)
    pay = deals.waiting_on_me(db, BUYER)["pay"]
    assert [(p["request_id"], p["seller_name"], p["price_cents"], p["cash"]) for p in pay] == [
        (deal["id"], "Seller", 2000, False)]
    assert deals.waiting_on_me(db, SELLER)["check_payment"] == []
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    check = deals.waiting_on_me(db, SELLER)["check_payment"]
    assert [(c["buyer_name"], c["title"], c["paid"]) for c in check] == [
        ("Buyer", "Desk lamp", True)]
    assert deals.waiting_on_me(db, BUYER)["pay"] == []


def test_waiting_on_me_shows_cash_deals_to_both(db):
    db.save_payment_methods(SELLER, {"accepts_cash": True})
    deal = start_purchase(db, a_listing(db), BUYER)
    deals.choose_cash(db, deal["id"], BUYER)
    assert deals.waiting_on_me(db, BUYER)["pay"][0]["cash"] is True
    check = deals.waiting_on_me(db, SELLER)["check_payment"][0]
    assert check["cash"] is True and check["paid"] is False


# --- a blocked seller ---------------------------------------------------------------

def test_nobody_can_start_buying_from_a_blocked_seller(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    db.listings[lid]["price_cents"] = 2000  # so it can also be bought at the listed price
    chat = a_chat(db, lid)
    db.profiles[SELLER]["blocked_at"] = "now"
    with pytest.raises(ListingError, match="seller isn't available"):
        deals.buy_now(db, BUYER, chat)
    with pytest.raises(ListingError, match="seller isn't available"):
        deals.buy_at_listed_price(db, BUYER, chat)
    assert db.requests == {} and db.get_listing(lid)["status"] != RESERVED


def test_buy_now_twice_says_you_already_started(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    chat = a_chat(db, lid)
    deals.buy_now(db, BUYER, chat)
    with pytest.raises(ListingError, match="already started buying"):
        deals.buy_now(db, BUYER, chat)


# --- Buy Now on the item page after a price was agreed ------------------------------

def test_buy_now_on_the_item_page_uses_the_price_agreed_in_the_chat(db):
    lid = a_listing(db)
    db.listings[lid]["price_cents"] = 5000
    give_bank_details(db, SELLER)
    chat = a_chat(db, lid, amount=4000)  # an accepted offer of 40
    deal = deals.buy_at_listed_price(db, BUYER, chat)
    assert deal["agreed_price_cents"] == 4000


# --- when saving the purchase fails --------------------------------------------------

def test_the_item_is_free_again_if_the_purchase_could_not_be_saved(db, monkeypatch):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    chat = a_chat(db, lid)

    def broken(row):
        raise RuntimeError("connection lost")
    monkeypatch.setattr(db, "insert_request", broken)
    with pytest.raises(RuntimeError):
        deals.buy_now(db, BUYER, chat)
    assert db.get_listing(lid)["status"] == "active"


# --- unpaid deals end for everybody ---------------------------------------------------

def test_an_unpaid_deal_ends_even_if_neither_side_opens_the_app(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    deal = deals.buy_now(db, BUYER, a_chat(db, lid))
    soon = datetime.now(timezone.utc) + timedelta(minutes=14)
    assert deals.cancel_all_overdue(db, soon) == 0
    assert db.get_listing(lid)["status"] == RESERVED
    late = datetime.now(timezone.utc) + timedelta(minutes=16)
    assert deals.cancel_all_overdue(db, late) == 1
    assert db.get_listing(lid)["status"] == "active"
    assert db.get_request(deal["id"])["status"] == "cancelled"


def test_a_paid_deal_is_never_ended_by_the_clock(db):
    lid = a_listing(db)
    give_bank_details(db, SELLER)
    deal = deals.buy_now(db, BUYER, a_chat(db, lid))
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    late = datetime.now(timezone.utc) + timedelta(minutes=16)
    assert deals.cancel_all_overdue(db, late) == 0
    assert db.get_listing(lid)["status"] == RESERVED


def test_waiting_on_me_says_when_each_deal_happened(db):
    deal = start_purchase(db, a_listing(db), BUYER)
    assert deals.waiting_on_me(db, BUYER)["pay"][0]["at"] is not None
    deals.mark_paid(db, deal["id"], BUYER, "bank")
    assert deals.waiting_on_me(db, SELLER)["check_payment"][0]["at"] is not None
