"""Tests for area 5 (Trust & safety: reports): accepted reports, refused reports.

Every test gets a fresh pretend database in memory (tests/fake_database.py),
so the real Supabase database is never touched.
Run them with:  pytest
"""

import pytest

import reports
from fake_database import FakeDatabase
from reports import NotAllowed, NotFound, ReportError

ANA = "ana@novasbe.pt"
TOM = "tom@novasbe.pt"
EVA = "eva@novasbe.pt"


@pytest.fixture
def db():
    """A pretend database with three students; Tom sells one listing."""
    db = FakeDatabase()
    db.add_profile(ANA, "Ana")
    db.add_profile(TOM, "Tom")
    db.add_profile(EVA, "Eva")
    db.tom_listing = db.add_listing(db.get_profile(TOM)["id"], "Old sofa")
    return db


def tom_id(db) -> int:
    return db.get_profile(TOM)["id"]


# --- accepted reports -----------------------------------------------------------

def test_report_a_listing(db):
    report_id = reports.create_report(db, ANA, listing_id=db.tom_listing["id"],
                                      reason="Scam or fake listing", details="  Asks for money first.  ")
    report = db.reports[report_id]
    assert report["reporter_id"] == db.get_profile(ANA)["id"]
    assert report["listing_id"] == db.tom_listing["id"]
    assert report["reported_profile_id"] is None
    assert report["reason"] == "Scam or fake listing"
    assert report["details"] == "Asks for money first."  # spaces trimmed
    assert report["status"] == "open"


def test_report_a_student_without_details(db):
    report_id = reports.create_report(db, ANA, reported_profile_id=tom_id(db), reason="Harassment")
    report = db.reports[report_id]
    assert report["reported_profile_id"] == tom_id(db)
    assert report["listing_id"] is None
    assert report["details"] is None


def test_two_students_can_report_the_same_listing(db):
    reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="Forbidden item")
    reports.create_report(db, EVA, listing_id=db.tom_listing["id"], reason="Forbidden item")
    assert len(db.reports) == 2


def test_details_of_exactly_500_characters_are_fine(db):
    reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="Other",
                          details="x" * 500)


def test_same_student_can_report_a_listing_and_its_seller(db):
    reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="Forbidden item")
    reports.create_report(db, ANA, reported_profile_id=tom_id(db), reason="Harassment")
    assert len(db.reports) == 2


def test_can_report_again_after_the_first_report_was_handled(db):
    first = reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="Other")
    db.reports[first]["status"] = "dismissed"
    reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="Other")
    assert len(db.reports) == 2


# --- who may report ---------------------------------------------------------------

def test_non_nova_email_cannot_report(db):
    with pytest.raises(NotAllowed):
        reports.create_report(db, "someone@gmail.com", listing_id=db.tom_listing["id"],
                              reason="Other")


def test_student_without_profile_cannot_report(db):
    with pytest.raises(NotAllowed):
        reports.create_report(db, "new@novasbe.pt", listing_id=db.tom_listing["id"],
                              reason="Other")


def test_cannot_report_your_own_listing(db):
    with pytest.raises(NotAllowed):
        reports.create_report(db, TOM, listing_id=db.tom_listing["id"], reason="Other")
    assert db.reports == {}


def test_cannot_report_yourself(db):
    with pytest.raises(NotAllowed):
        reports.create_report(db, TOM, reported_profile_id=tom_id(db), reason="Other")
    assert db.reports == {}


# --- what is reported -----------------------------------------------------------

def test_needs_a_target(db):
    with pytest.raises(ReportError):
        reports.create_report(db, ANA, reason="Other")


def test_cannot_report_a_listing_and_a_student_at_once(db):
    with pytest.raises(ReportError):
        reports.create_report(db, ANA, listing_id=db.tom_listing["id"],
                              reported_profile_id=tom_id(db), reason="Other")


def test_listing_must_exist(db):
    with pytest.raises(NotFound):
        reports.create_report(db, ANA, listing_id=9999, reason="Other")


def test_student_must_exist(db):
    with pytest.raises(NotFound):
        reports.create_report(db, ANA, reported_profile_id=9999, reason="Other")


# --- input rules ------------------------------------------------------------------

def test_reason_must_be_from_the_list(db):
    with pytest.raises(ReportError) as caught:
        reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="I don't like it")
    assert caught.value.errors == ["Choose a reason from the list."]


def test_details_at_most_500_characters(db):
    with pytest.raises(ReportError) as caught:
        reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="Other",
                              details="x" * 501)
    assert caught.value.errors == ["Details must be at most 500 characters."]


def test_every_problem_is_reported_at_once(db):
    with pytest.raises(ReportError) as caught:
        reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="",
                              details="x" * 501)
    assert len(caught.value.errors) == 2
    assert db.reports == {}


# --- no repeats -----------------------------------------------------------------

def test_same_student_cannot_report_the_same_listing_twice(db):
    reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="Forbidden item")
    with pytest.raises(ReportError) as caught:
        reports.create_report(db, ANA, listing_id=db.tom_listing["id"], reason="Other")
    assert caught.value.errors == ["You already reported this. An admin will look at it."]
    assert len(db.reports) == 1


def test_same_student_cannot_report_the_same_student_twice(db):
    reports.create_report(db, ANA, reported_profile_id=tom_id(db), reason="Harassment")
    with pytest.raises(ReportError):
        reports.create_report(db, ANA, reported_profile_id=tom_id(db), reason="Harassment")
    assert len(db.reports) == 1
