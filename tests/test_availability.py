"""Tests for the 'available from' date: the text shown to buyers, and that a
seller's chosen date is stored. Uses the in-memory fake database for the create
tests, so the real Supabase is never touched."""

from datetime import date, timedelta
from io import BytesIO

from PIL import Image

import listings
from deal_helpers import give_bank_details
from fake_database import FakeDatabase

TODAY = date(2026, 12, 1)


# --- availability_text (pure) -------------------------------------------------
def test_available_now_when_there_is_no_date():
    assert listings.availability_text({}, TODAY) == ""
    assert listings.availability_text({"available_from": None}, TODAY) == ""


def test_available_now_when_the_date_is_today_or_past():
    assert listings.availability_text({"available_from": "2026-12-01"}, TODAY) == ""  # today
    assert listings.availability_text({"available_from": "2026-11-01"}, TODAY) == ""  # past


def test_shows_a_future_date():
    out = listings.availability_text({"available_from": "2026-12-10"}, TODAY)
    assert out == "Available from 10 Dec 2026"


def test_accepts_a_date_object_too():
    out = listings.availability_text({"available_from": date(2026, 12, 10)}, TODAY)
    assert out == "Available from 10 Dec 2026"


# --- listed_text (pure) -------------------------------------------------------
def test_listed_text_from_an_iso_timestamp():
    # created_at comes back from the database as a full ISO timestamp.
    out = listings.listed_text({"created_at": "2026-11-20T15:13:51.123456+00:00"})
    assert out == "Listed on 20 Nov 2026"


def test_listed_text_accepts_a_date_object():
    assert listings.listed_text({"created_at": date(2026, 11, 20)}) == "Listed on 20 Nov 2026"


def test_listed_text_is_empty_without_a_date():
    assert listings.listed_text({}) == ""
    assert listings.listed_text({"created_at": None}) == ""


# --- create_listing stores the date -------------------------------------------
def photo() -> bytes:
    out = BytesIO()
    Image.new("RGB", (40, 30), (200, 50, 50)).save(out, format="JPEG")
    return out.getvalue()


GOOD = dict(title="A good test title", description="A description long enough to pass.",
            free=False, price_cents=2000, category=listings.CATEGORIES[0],
            condition=listings.CONDITIONS[0], pickup_area=listings.PICKUP_AREAS[0])


def _db():
    db = FakeDatabase()
    db.add_profile("ana@novasbe.pt")
    give_bank_details(db, "ana@novasbe.pt")  # needed to sell for money
    return db


def test_create_listing_keeps_the_chosen_date():
    db = _db()
    lid = listings.create_listing(db, "ana@novasbe.pt", **GOOD, photos=[photo()],
                                  available_from=date(2026, 12, 10))
    assert db.get_listing(lid)["available_from"] == "2026-12-10"


def test_create_listing_without_a_date_stores_none():
    db = _db()
    lid = listings.create_listing(db, "ana@novasbe.pt", **GOOD, photos=[photo()])
    assert db.get_listing(lid)["available_from"] is None


# --- "available until" -------------------------------------------------------

def test_until_text():
    out = listings.availability_text({"available_until": "2026-12-20"}, TODAY)
    assert out == "Available until 20 Dec 2026"


def test_from_and_until_text():
    out = listings.availability_text({"available_from": "2026-12-10",
                                      "available_until": "2026-12-20"}, TODAY)
    assert out == "Available from 10 Dec 2026 until 20 Dec 2026"


def test_until_passed_text_and_expired():
    item = {"available_until": "2026-11-30"}
    assert listings.availability_text(item, TODAY) == "Was available until 30 Nov 2026"
    assert listings.expired(item, TODAY)
    assert not listings.expired({"available_until": "2026-12-01"}, TODAY)  # the last day itself
    assert not listings.expired({}, TODAY)


def test_create_listing_keeps_the_until_date():
    db = _db()
    until = date.today() + timedelta(days=10)
    lid = listings.create_listing(db, "ana@novasbe.pt", **GOOD, photos=[photo()],
                                  available_until=until)
    assert db.get_listing(lid)["available_until"] == until.isoformat()


def test_until_in_the_past_is_refused():
    errors = listings.check_listing(**GOOD, available_until=date.today() - timedelta(days=1))
    assert any("already passed" in e for e in errors)


def test_until_before_from_is_refused():
    start = date.today() + timedelta(days=10)
    errors = listings.check_listing(**GOOD, available_from=start,
                                    available_until=start - timedelta(days=1))
    assert any("before Available from" in e for e in errors)


def test_expired_items_are_hidden_on_browse():
    import browsing
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    items = [{"id": 1, "title": "a", "price_cents": 0, "available_until": yesterday},
             {"id": 2, "title": "b", "price_cents": 0, "available_until": date.today().isoformat()},
             {"id": 3, "title": "c", "price_cents": 0}]
    assert {item["id"] for item in browsing.search_and_sort(items)} == {2, 3}
