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
    """A free item, so no Nova credits are involved."""
    return db.insert_listing({
        "seller_id": db.get_profile(SELLER)["id"], "title": title, "photo_paths": [],
        "price_cents": 0, "category": "Furniture", "pickup_area": "Carcavelos",
    })["id"]


def page_text(page) -> str:
    return "\n".join(element.value for element in [*page.markdown, *page.caption])


def test_requests_and_sales_show_inside_the_listing_cards(db):
    lamp, bike, chair = listing(db, "Desk lamp"), listing(db, "Bike"), listing(db, "Old chair")
    deals.request_to_buy(db, lamp, "ana@novasbe.pt")                 # waiting for an answer
    accepted = deals.request_to_buy(db, bike, "rui@novasbe.pt")      # reserved for Rui
    deals.accept_request(db, accepted["id"], SELLER)
    sold = deals.request_to_buy(db, chair, "marta@novasbe.pt")       # sold to Marta
    deals.accept_request(db, sold["id"], SELLER)
    deals.confirm_sold(db, sold["id"], SELLER)
    deals.confirm_received(db, sold["id"], "marta@novasbe.pt")

    page = AppTest.from_file(PAGE, default_timeout=30).run()

    assert not page.exception
    assert [tab.label for tab in page.tabs] == ["Active (1) 🔔", "Reserved (1)", "Sold (1)"]
    text = page_text(page)
    assert "**Ana** wants to buy this." in text
    assert "**Rui** wants to buy this." in text
    assert "Sold to Marta" in text
    labels = [button.label for button in page.button]
    assert "Accept" in labels and "Decline" in labels
    assert "I handed it over" in labels and "Cancel deal" in labels
    # With an accepted buyer, the deal decides: no Reserve/Sold/Relist on the bike.
    assert f"sold-{bike}" not in [button.key for button in page.button]


def test_accepting_a_buyer_on_the_page_reserves_the_item(db):
    lamp = listing(db, "Desk lamp")
    request = deals.request_to_buy(db, lamp, "ana@novasbe.pt")

    page = AppTest.from_file(PAGE, default_timeout=30).run()
    page.button(key=f"accept-{request['id']}").click().run()

    assert not page.exception
    assert db.get_request(request["id"])["status"] == deals.ACCEPTED
    assert [tab.label for tab in page.tabs] == ["Active (0)", "Reserved (1)", "Sold (0)"]
    assert page.success[0].value == "Accepted. The item is now reserved for this buyer."

