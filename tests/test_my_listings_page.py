"""Tests for the "My listings" page (views/my_listings.py): your listings and the
buyers who asked for them are on one page. Uses the in-memory fake database, so
the real Supabase is never touched.  Run them with:  pytest
"""

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import accounts
import deals
from deal_helpers import finish_purchase, start_purchase
from fake_database import FakeDatabase

SELLER = "seller@novasbe.pt"
PAGE = str(Path(__file__).resolve().parents[1] / "views" / "my_listings.py")


@pytest.fixture
def db(monkeypatch):
    db = FakeDatabase()
    db.add_profile(SELLER, "Seller")
    db.add_profile("ana@novasbe.pt", "Ana")
    db.add_profile("rui@novasbe.pt", "Rui")
    db.add_profile("marta@novasbe.pt", "Marta")
    # The page asks "who is logged in?" and reads from the database: both are faked.
    monkeypatch.setattr(accounts, "logged_in_user", lambda: None)
    monkeypatch.setattr(accounts, "verified_nova_email", lambda user: SELLER)
    monkeypatch.setitem(sys.modules, "database", db)
    return db


def listing(db, title):
    return db.insert_listing({
        "seller_id": db.get_profile(SELLER)["id"], "title": title, "photo_paths": [],
        "price_cents": 0, "category": "Furniture", "pickup_area": "Carcavelos",
    })["id"]


def page_text(page) -> str:
    return "\n".join(element.value for element in [*page.markdown, *page.caption])


def test_buyers_and_sales_show_inside_the_listing_cards(db):
    lamp, bike, chair = listing(db, "Desk lamp"), listing(db, "Bike"), listing(db, "Old chair")
    db.insert_request({"listing_id": lamp,                            # an old request
                       "buyer_id": db.get_profile("ana@novasbe.pt")["id"]})
    paying = start_purchase(db, bike, "rui@novasbe.pt")               # Rui says he paid
    deals.mark_paid(db, paying["id"], "rui@novasbe.pt", "bank")
    sold = start_purchase(db, chair, "marta@novasbe.pt")              # sold to Marta
    finish_purchase(db, sold["id"], "marta@novasbe.pt", SELLER)

    page = AppTest.from_file(PAGE, default_timeout=30).run()

    assert not page.exception
    assert [tab.label.split(" 🔔")[0] for tab in page.tabs] == [
        "Active (1)", "Reserved (1)", "Sold (1)"]
    text = page_text(page)
    assert "**Ana** asked to buy this (old request)" in text
    assert "**Rui** is buying this." in text
    assert "Sold to Marta" in text
    labels = [button.label for button in page.button]
    assert "Decline" in labels
    assert "Payment received" in labels and "Not received yet" in labels
    # With a buyer, the deal decides: no Reserve/Sold/Relist on the bike.
    assert f"sold-{bike}" not in [button.key for button in page.button]


def test_confirming_the_payment_on_the_page_marks_it_sold(db):
    bike = listing(db, "Bike")
    deal = start_purchase(db, bike, "rui@novasbe.pt")
    deals.mark_paid(db, deal["id"], "rui@novasbe.pt", "bank")

    page = AppTest.from_file(PAGE, default_timeout=30).run()
    page.button(key=f"mylistings-received-{deal['id']}").click().run()

    assert not page.exception
    assert db.get_request(deal["id"])["status"] == deals.COMPLETED
    assert db.get_listing(bike)["status"] == "sold"
    assert page.success[0].value == "Payment confirmed. The item is marked sold."
