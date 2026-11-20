"""Tests for the admin page rules (area 5, Trust & safety: handling reports).

Every test gets a fresh pretend database in memory (tests/fake_database.py),
so the real Supabase database is never touched. The admin list normally
comes from .streamlit/secrets.toml; here it is replaced with one address.
Run them with:  pytest
"""

import pytest

import admin
import listings
import reports
from fake_database import FakeDatabase

BOSS = "boss@novasbe.pt"  # the admin
ANA = "ana@novasbe.pt"
TOM = "tom@novasbe.pt"
EVA = "eva@novasbe.pt"


@pytest.fixture(autouse=True)
def only_boss_is_admin(monkeypatch):
    """Pretend .streamlit/secrets.toml lists BOSS as the only admin."""
    monkeypatch.setattr(admin, "admin_emails", lambda: [BOSS])


@pytest.fixture
def db():
    """Four students; Tom sells a sofa with one photo; Ana reported it."""
    db = FakeDatabase()
    db.add_profile(BOSS, "Boss")
    db.add_profile(ANA, "Ana")
    db.add_profile(TOM, "Tom")
    db.add_profile(EVA, "Eva")
    db.photos["sofa.jpg"] = b"picture"
    db.tom_listing = db.insert_listing({"seller_id": tom_id(db), "title": "Old sofa",
                                        "photo_paths": ["sofa.jpg"]})
    db.report_id = reports.create_report(db, ANA, listing_id=db.tom_listing["id"],
                                         reason="Scam or fake listing", details="Asks for money first.")
    return db


def tom_id(db) -> int:
    return db.get_profile(TOM)["id"]


# --- only admins ------------------------------------------------------------------

@pytest.mark.parametrize("who", [ANA, TOM, "", None, "boss@gmail.com"])
def test_non_admins_are_refused_for_every_action(db, who):
    with pytest.raises(admin.NotAllowed):
        admin.open_reports(db, who)
    for action in (admin.remove_listing, admin.block_user, admin.dismiss_report):
        with pytest.raises(admin.NotAllowed):
            action(db, who, db.report_id)
    # Nothing changed.
    assert db.reports[db.report_id]["status"] == "open"
    assert db.tom_listing["id"] in db.listings
    assert db.get_profile(TOM)["blocked_at"] is None


def test_nobody_is_admin_without_an_admin_list(db, monkeypatch):
    monkeypatch.setattr(admin, "admin_emails", lambda: [])
    with pytest.raises(admin.NotAllowed):
        admin.dismiss_report(db, BOSS, db.report_id)


def test_admin_email_is_matched_without_caring_about_case(db):
    admin.dismiss_report(db, "Boss@NovaSBE.pt", db.report_id)
    assert db.reports[db.report_id]["status"] == "dismissed"


# --- open reports -----------------------------------------------------------------

def test_open_reports_oldest_first_with_what_to_show(db):
    reports.create_report(db, EVA, reported_profile_id=tom_id(db), reason="Harassment")
    shown = admin.open_reports(db, BOSS)
    assert [r["kind"] for r in shown] == ["listing", "student"]
    first, second = shown
    assert first["what"] == "Old sofa"
    assert first["reason"] == "Scam or fake listing"
    assert first["details"] == "Asks for money first."
    assert first["reporter"] == "Ana"
    assert second["what"] == "Tom"
    assert second["reporter"] == "Eva"
    assert first["created_at"] < second["created_at"]


def test_handled_reports_are_not_shown(db):
    admin.dismiss_report(db, BOSS, db.report_id)
    assert admin.open_reports(db, BOSS) == []


# --- dismiss --------------------------------------------------------------------

def test_dismiss_sets_status_and_handled_at(db):
    admin.dismiss_report(db, BOSS, db.report_id)
    report = db.reports[db.report_id]
    assert report["status"] == "dismissed"
    assert report["handled_at"] is not None


def test_a_report_cannot_be_handled_twice(db):
    admin.dismiss_report(db, BOSS, db.report_id)
    with pytest.raises(admin.NotFound):
        admin.dismiss_report(db, BOSS, db.report_id)


def test_unknown_report(db):
    with pytest.raises(admin.NotFound):
        admin.dismiss_report(db, BOSS, 9999)


# --- remove listing ---------------------------------------------------------------

def test_remove_listing_deletes_it_and_its_photos(db):
    admin.remove_listing(db, BOSS, db.report_id)
    assert db.tom_listing["id"] not in db.listings
    assert "sofa.jpg" not in db.photos
    # The report went with the listing ("on delete cascade").
    assert db.report_id not in db.reports


def test_remove_listing_needs_a_listing_report(db):
    student_report = reports.create_report(db, EVA, reported_profile_id=tom_id(db),
                                           reason="Harassment")
    with pytest.raises(admin.NotAllowed):
        admin.remove_listing(db, BOSS, student_report)


# --- block user -------------------------------------------------------------------

def test_block_from_a_listing_report_blocks_the_seller(db):
    admin.block_user(db, BOSS, db.report_id)
    assert db.get_profile(TOM)["blocked_at"] is not None
    report = db.reports[db.report_id]
    assert report["status"] == "blocked"
    assert report["handled_at"] is not None


def test_block_closes_all_open_reports_about_that_student(db):
    about_tom = reports.create_report(db, EVA, reported_profile_id=tom_id(db), reason="Harassment")
    about_ana = reports.create_report(db, EVA, reported_profile_id=db.get_profile(ANA)["id"],
                                      reason="Other")
    admin.block_user(db, BOSS, about_tom)
    assert db.reports[about_tom]["status"] == "blocked"
    assert db.reports[db.report_id]["status"] == "blocked"  # about Tom's listing
    assert db.reports[about_ana]["status"] == "open"  # someone else: untouched
    assert db.get_profile(ANA)["blocked_at"] is None


def test_admin_cannot_block_themselves(db):
    about_boss = reports.create_report(db, ANA, reported_profile_id=db.get_profile(BOSS)["id"],
                                       reason="Other")
    with pytest.raises(admin.NotAllowed):
        admin.block_user(db, BOSS, about_boss)
    assert db.get_profile(BOSS)["blocked_at"] is None


# --- what a blocked student can no longer do ----------------------------------------

def test_blocked_sellers_listings_are_left_out_of_the_feed(db):
    db.add_listing(db.get_profile(ANA)["id"], "Desk lamp")
    admin.block_user(db, BOSS, db.report_id)
    titles = [listing["title"] for listing in listings.feed_listings(db)]
    assert titles == ["Desk lamp"]
    assert db.get_active_listings(tom_id(db)) == []


def test_blocked_seller_cannot_create_a_listing(db):
    admin.block_user(db, BOSS, db.report_id)
    with pytest.raises(listings.NotAllowed):
        listings.create_listing(db, TOM, title="Another sofa", description="A very nice sofa.",
                                free=True, price_cents=0, category="Furniture",
                                condition="Good", pickup_area="Carcavelos", photos=[])


def test_blocked_reporter_cannot_send_a_report(db):
    admin.block_user(db, BOSS, db.report_id)
    with pytest.raises(reports.NotAllowed):
        reports.create_report(db, TOM, reported_profile_id=db.get_profile(ANA)["id"],
                              reason="Other")


# --- blocking calls off the student's deals -------------------------------------

def test_blocking_cancels_the_deals_of_the_blocked_student(db):
    import deals
    request = deals.request_to_buy(db, db.tom_listing["id"], EVA)
    admin.block_user(db, BOSS, db.report_id)
    assert db.get_request(request["id"])["status"] == "cancelled"
    assert deals.my_purchases(db, EVA)[0]["status"] == "cancelled"
