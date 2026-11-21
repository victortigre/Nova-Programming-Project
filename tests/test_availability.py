"""Tests for the 'available from' date: the text shown to buyers, and that a
seller's chosen date is stored. Uses the in-memory fake database for the create
tests, so the real Supabase is never touched."""

from datetime import date
from io import BytesIO

from PIL import Image

import listings
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
