"""Admin: what an admin does with the reports students send.

Feature (area 5 of the MVP, Trust & safety):
    open_reports     every report nobody handled yet, oldest first
    remove_listing   delete the reported listing and its photos
    block_user       block the reported student (for a listing: its seller)
                     and call off every deal they are in
    dismiss_report   close the report without doing anything else
    disputed_returns refunds where the seller says the item came back damaged
    settle_return    decide one: refund the buyer, or pay the seller

Rules that keep this safe:
* Only admins may do any of this. Who is an admin is written in
  .streamlit/secrets.toml (see accounts.admin_emails). Every function below
  checks it again FIRST, so hiding the Admin page is not the only protection.
* The pages pass the email from the login, never one typed into a form.
* An admin cannot block themselves.
* A report can only be handled once: after that it is no longer "open".

Storage: like reports.py, this file never talks to Supabase itself. Every
function takes `db` first: the `database` module in the pages, or the
pretend database in the tests (tests/fake_database.py).
"""

import deals
from accounts import admin_emails, is_admin

OPEN = "open"
BLOCKED = "blocked"
DISMISSED = "dismissed"


class NotAllowed(PermissionError):
    """The person isn't allowed to do this (for example, not an admin)."""


class NotFound(LookupError):
    """The report, listing or student doesn't exist (any more), or the report was already handled."""


def _check_admin(admin_email: str) -> None:
    """Stop right here unless this email is on the admin list."""
    if not is_admin(admin_email, admin_emails()):
        raise NotAllowed("Only admins can do this.")


def _open_report(db, report_id: int) -> dict:
    """The report with this number, if it is still open. Otherwise NotFound."""
    report = db.get_report(report_id)
    if report is None or report["status"] != OPEN:
        raise NotFound("This report doesn't exist or was already handled.")
    return report


def _reported_student_id(db, report: dict) -> int:
    """The profile number of the student a report is about.

    For a report about a student, that student. For a report about a
    listing, the student who sells it.
    """
    if report["reported_profile_id"] is not None:
        return report["reported_profile_id"]
    listing = db.get_listing(report["listing_id"])
    if listing is None:
        raise NotFound("The reported listing doesn't exist any more.")
    return listing["seller_id"]


# --- reading ----------------------------------------------------------------------

def open_reports(db, admin_email: str) -> list[dict]:
    """Every open report, oldest first, with what the page needs to show it.

    Each item has: id, kind ("listing" or "student"), what (the listing's
    title or the student's name), reason, details, reporter (name) and
    created_at.
    """
    _check_admin(admin_email)
    shown = []
    for report in db.open_reports():
        if report["listing_id"] is not None:
            kind = "listing"
            listing = db.get_listing(report["listing_id"])
            what = listing["title"] if listing else "(listing removed)"
        else:
            kind = "student"
            student = db.get_profile_by_id(report["reported_profile_id"])
            what = student["name"] if student else "(student removed)"
        reporter = db.get_profile_by_id(report["reporter_id"])
        shown.append({
            "id": report["id"],
            "kind": kind,
            "what": what,
            "reason": report["reason"],
            "details": report["details"],
            "reporter": reporter["name"] if reporter else "(student removed)",
            "created_at": report["created_at"],
        })
    return shown


# --- handling a report --------------------------------------------------------------

def remove_listing(db, admin_email: str, report_id: int) -> None:
    """Delete the reported listing and its photos for good."""
    _check_admin(admin_email)
    report = _open_report(db, report_id)
    if report["listing_id"] is None:
        raise NotAllowed("This report is about a student, not a listing.")
    listing = db.get_listing(report["listing_id"])
    if listing is None:
        raise NotFound("The reported listing doesn't exist any more.")

    # Order matters:
    # 1. Delete the listing first. The database then also deletes every
    #    report about it ("on delete cascade"), this one included. That is
    #    fine: the problem is gone, so there is nothing left to handle.
    #    So we do not mark the report "removed" first: if the delete then
    #    failed, the report would be closed while the listing is still there.
    # 2. Delete the photos last. If that step fails, only some unused files
    #    stay behind; nobody sees a listing with missing photos.
    # 0. Call off the live deals on it first, so a buyer's held credits go back
    #    to them (deleting the listing also deletes its deals).
    for request in db.requests_for_listing(listing["id"], list(deals.LIVE)):
        deals._call_off(db, request, listing)
    db.admin_delete_listing(listing["id"])
    db.delete_listing_photos(listing["photo_paths"])


def block_user(db, admin_email: str, report_id: int) -> None:
    """Block the reported student and close every open report about them."""
    _check_admin(admin_email)
    report = _open_report(db, report_id)
    student_id = _reported_student_id(db, report)
    student = db.get_profile_by_id(student_id)
    if student is None:
        raise NotFound("This student doesn't exist any more.")
    if is_admin(student["email"], [admin_email]):
        raise NotAllowed("You cannot block yourself.")

    # Block first, then close the reports. If closing failed, the student is
    # still blocked and the reports simply stay open for another look.
    db.block_profile(student_id)

    # Nobody should keep waiting for a blocked student: their requests are
    # cancelled, and so are other students' requests for their items.
    deals.cancel_deals_of(db, student_id)

    # The open reports about this student: about them directly, or about one
    # of their listings. This report is one of them.
    their_listings = {listing["id"] for listing in db.listings_of_seller(student_id)}
    about_them = [
        r["id"] for r in db.open_reports()
        if r["reported_profile_id"] == student_id or r["listing_id"] in their_listings
    ]
    db.close_reports(about_them, BLOCKED)


def dismiss_report(db, admin_email: str, report_id: int) -> None:
    """Close the report: the admin looked at it and nothing needs to be done."""
    _check_admin(admin_email)
    _open_report(db, report_id)
    db.close_reports([report_id], DISMISSED)


# --- returns the seller reported (the item came back in a worse condition) -------

def disputed_returns(db, admin_email: str) -> list[dict]:
    """Every reported return, oldest first, with what the page needs to show it.

    Each item has: id, title, price_cents, buyer, seller, asked_at (refund asked),
    given_back_at, reported_at and reason (why the buyer asked for a refund).
    """
    _check_admin(admin_email)
    rows = db.disputed_returns()
    names = db.names_of([r["buyer_id"] for r in rows] + [r["listings"]["seller_id"] for r in rows])
    return [{
        "id": r["id"],
        "title": r["listings"].get("title", ""),
        "price_cents": r["listings"].get("price_cents", 0),
        "buyer": names.get(r["buyer_id"], "(student removed)"),
        "seller": names.get(r["listings"]["seller_id"], "(student removed)"),
        "asked_at": r.get("returned_at"),
        "given_back_at": r.get("given_back_at"),
        "reported_at": r.get("return_disputed_at"),
        "reason": deals.refund_reason_text(r),
    } for r in rows]


def settle_return(db, admin_email: str, request_id: int, refund_buyer: bool) -> None:
    """Decide a reported return: give the held credits back to the buyer
    (the listing is active again), or pay the seller (the listing is sold)."""
    _check_admin(admin_email)
    try:
        deals.settle_dispute(db, request_id, refund_buyer)
    except deals.ListingError as exc:
        raise NotFound(" ".join(exc.errors)) from exc
