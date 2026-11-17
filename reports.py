"""Reports: a student tells the admins about a bad listing or another student.

Feature (area 5 of the MVP, Trust & safety):
    create_report   report one listing OR one student, with a reason from
                    the list and optional details

Rules that keep this safe:
* The reporter must be a Nova address with a profile. The pages pass the
  email from the login (accounts.verified_nova_email), never one typed into
  a form, so nobody can send a report in someone else's name.
* A report is about exactly one thing: a listing or a student, and that
  thing must exist.
* You cannot report yourself or your own listing.
* A student blocked by an admin cannot send reports.
* The same student cannot send a second report about the same thing while
  the first one is still open. Different students can each report it.

Storage: like listings.py, this file never talks to Supabase itself. Every
function takes `db` first: the `database` module in the pages, or the
pretend database in the tests (tests/fake_database.py).
"""

from accounts import nova_email

REASONS = [
    "Forbidden item",
    "Scam or fake listing",
    "Offensive content",
    "Harassment",
    "Other",
]
MAX_DETAILS_LENGTH = 500

OPEN = "open"


class ReportError(ValueError):
    """The input breaks one or more rules. `errors` lists every problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


class NotAllowed(PermissionError):
    """The person isn't allowed to send this report."""


class NotFound(LookupError):
    """The listing or student being reported doesn't exist (any more)."""


def check_report(*, reason, details) -> list[str]:
    """Every problem with the reason and details (empty list = all good)."""
    errors = []
    if reason not in REASONS:
        errors.append("Choose a reason from the list.")
    if len((details or "").strip()) > MAX_DETAILS_LENGTH:
        errors.append(f"Details must be at most {MAX_DETAILS_LENGTH} characters.")
    return errors


def _reporter_profile(db, email: str) -> dict:
    """The profile of the person reporting. Every report belongs to a profile."""
    reporter = nova_email({"email": email})
    if reporter is None:
        raise NotAllowed("Only @novasbe.pt accounts can send reports.")
    profile = db.get_profile(reporter)
    if profile is None:
        raise NotAllowed("Fill in your profile before you send a report.")
    if profile.get("blocked_at"):  # an admin blocked this student (see admin.py)
        raise NotAllowed("Your account has been blocked, so you cannot send reports.")
    return profile


def create_report(db, reporter_email: str, *, listing_id: int | None = None,
                  reported_profile_id: int | None = None, reason: str,
                  details: str = "") -> int:
    """Send a report about one listing or one student. Returns the report's id.

    Raises ReportError listing every input problem, NotAllowed or NotFound.
    """
    reporter = _reporter_profile(db, reporter_email)

    # Exactly one target: a listing or a student.
    if (listing_id is None) == (reported_profile_id is None):
        raise ReportError(["Report either a listing or a student."])

    # The target must exist, and it must not be you or your own listing.
    if listing_id is not None:
        listing = db.get_listing(listing_id)
        if listing is None:
            raise NotFound("This listing doesn't exist any more.")
        if listing["seller_id"] == reporter["id"]:
            raise NotAllowed("You cannot report your own listing.")
    else:
        if db.get_profile_by_id(reported_profile_id) is None:
            raise NotFound("This student doesn't exist.")
        if reported_profile_id == reporter["id"]:
            raise NotAllowed("You cannot report yourself.")

    errors = check_report(reason=reason, details=details)
    if errors:
        raise ReportError(errors)

    # One open report per student per target is enough.
    if db.open_report(reporter["id"], listing_id, reported_profile_id) is not None:
        raise ReportError(["You already reported this. An admin will look at it."])

    row = {
        "reporter_id": reporter["id"],
        "listing_id": listing_id,
        "reported_profile_id": reported_profile_id,
        "reason": reason,
        "details": (details or "").strip() or None,  # nothing typed -> no details
    }
    return db.insert_report(row)["id"]
