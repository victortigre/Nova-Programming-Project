"""Database: the only file that talks to Supabase.

Supabase is the online service that stores our tables and photos. The
tables are created once with database_setup.sql.

The key this file uses may read and change everything in the database.
That is why it stays in .streamlit/secrets.toml, and why the pages decide
who may do what before they call a function from here: a page always
passes the email it got from the login, never one typed into a form.
"""

import uuid
from datetime import date, datetime, timezone

import streamlit as st
from supabase import Client, create_client

PHOTO_BUCKET = "profile-photos"
LISTING_PHOTO_BUCKET = "listing-photos"
PHOTO_LINK_SECONDS = 3600  # a photo link works for one hour


def database_is_set_up() -> bool:
    """True when .streamlit/secrets.toml holds real database settings."""
    try:
        settings = st.secrets["supabase"]
        values = [settings["url"], settings["secret_key"]]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return False
    return all(value and "PASTE" not in value for value in values)


@st.cache_resource
def _client() -> Client:
    """Connect to Supabase once and reuse the connection afterwards."""
    settings = st.secrets["supabase"]
    return create_client(settings["url"], settings["secret_key"])


# --- Profiles -----------------------------------------------------------------


def get_profile(email: str) -> dict | None:
    """Return the profile that belongs to this email, or None if there is none."""
    rows = _client().table("profiles").select("*").eq("email", email).execute().data
    return rows[0] if rows else None


def get_profile_by_id(profile_id: int) -> dict | None:
    """Return the profile with this number, or None if there is none."""
    rows = _client().table("profiles").select("*").eq("id", profile_id).execute().data
    return rows[0] if rows else None


def save_profile(
    email: str,
    name: str,
    program: str,
    leaving_lisbon_on: date | None,
    photo_path: str | None,
) -> dict:
    """Create the profile for this email, or change it if it already exists."""
    row = {
        "email": email,
        "name": name,
        "program": program,
        "leaving_lisbon_on": leaving_lisbon_on.isoformat() if leaving_lisbon_on else None,
        "photo_path": photo_path,
    }
    saved = _client().table("profiles").upsert(row, on_conflict="email").execute().data
    return saved[0]


# --- Listings -----------------------------------------------------------------
#
# The rules (who may change a listing, what a valid listing is) are in
# listings.py. The functions that change a listing also need the seller's
# profile number, so a listing can only ever be changed by its own seller.


def insert_listing(row: dict) -> dict:
    """Store a new listing and return it, with its new id."""
    return _client().table("listings").insert(row).execute().data[0]


def get_listing(listing_id: int) -> dict | None:
    """Return the listing with this number, or None if there is none."""
    rows = _client().table("listings").select("*").eq("id", listing_id).execute().data
    return rows[0] if rows else None


def listings_of_seller(seller_id: int) -> list[dict]:
    """Return every listing of one seller, newest first."""
    return (
        _client().table("listings").select("*").eq("seller_id", seller_id)
        .order("created_at", desc=True).order("id", desc=True)
        .execute().data
    )


# Listings of a blocked seller are never shown to others. "profiles!inner"
# joins each listing to its seller's profile and drops listings whose seller
# does not match the filter "blocked_at is null" (= not blocked).
NOT_BLOCKED_SELLER = "*, profiles!inner(blocked_at)"


def feed_listings(limit: int, offset: int) -> list[dict]:
    """Return the listings buyers may see (not sold, seller not blocked), newest first."""
    return (
        _client().table("listings").select(NOT_BLOCKED_SELLER)
        .is_("profiles.blocked_at", "null").neq("status", "sold")
        .order("created_at", desc=True).order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute().data
    )


def get_active_listings(profile_id: int) -> list[dict]:
    """Return the active listings of one student (none if blocked), newest first."""
    return (
        _client().table("listings").select(NOT_BLOCKED_SELLER)
        .is_("profiles.blocked_at", "null")
        .eq("seller_id", profile_id).eq("status", "active")
        .order("created_at", desc=True)
        .execute().data
    )


def update_listing(listing_id: int, seller_id: int, changes: dict) -> None:
    """Change a listing. Nothing happens if the listing belongs to someone else."""
    changes = {**changes, "updated_at": datetime.now(timezone.utc).isoformat()}
    (
        _client().table("listings").update(changes)
        .eq("id", listing_id).eq("seller_id", seller_id)
        .execute()
    )


def delete_listing(listing_id: int, seller_id: int) -> None:
    """Remove a listing. Nothing happens if the listing belongs to someone else."""
    _client().table("listings").delete().eq("id", listing_id).eq("seller_id", seller_id).execute()


# --- Favourites ----------------------------------------------------------------
#
# A buyer's saved listings (their wishlist). Which rows a buyer may touch is
# decided by the page (it passes the profile from the login); here we just store.


def add_favorite(profile_id: int, listing_id: int) -> None:
    """Save a listing for a buyer. Saving the same one twice keeps a single row."""
    (
        _client().table("favorites")
        .upsert({"profile_id": profile_id, "listing_id": listing_id},
                on_conflict="profile_id,listing_id")
        .execute()
    )


def remove_favorite(profile_id: int, listing_id: int) -> None:
    """Remove a saved listing."""
    (
        _client().table("favorites").delete()
        .eq("profile_id", profile_id).eq("listing_id", listing_id)
        .execute()
    )


def favorite_ids(profile_id: int) -> list[int]:
    """The ids of the listings this buyer saved, newest-saved first."""
    rows = (
        _client().table("favorites").select("listing_id")
        .eq("profile_id", profile_id).order("id", desc=True)
        .execute().data
    )
    return [row["listing_id"] for row in rows]


def favorite_listings(profile_id: int) -> list[dict]:
    """The buyer's saved listings in full, newest-saved first."""
    ids = favorite_ids(profile_id)
    if not ids:
        return []
    rows = _client().table("listings").select("*").in_("id", ids).execute().data
    order = {listing_id: position for position, listing_id in enumerate(ids)}
    return sorted(rows, key=lambda row: order.get(row["id"], len(ids)))
# --- Reports ------------------------------------------------------------------
#
# The rules (who may report what) are in reports.py. A report points to a
# listing OR to a student, never both.


def insert_report(row: dict) -> dict:
    """Store a new report and return it, with its new id."""
    return _client().table("reports").insert(row).execute().data[0]


def open_report(
    reporter_id: int, listing_id: int | None, reported_profile_id: int | None
) -> dict | None:
    """Return this student's open report about this listing or student, or None."""
    query = (
        _client().table("reports").select("*")
        .eq("reporter_id", reporter_id).eq("status", "open")
    )
    if listing_id is not None:
        query = query.eq("listing_id", listing_id)
    else:
        query = query.eq("reported_profile_id", reported_profile_id)
    rows = query.limit(1).execute().data
    return rows[0] if rows else None


# --- Admin --------------------------------------------------------------------
#
# The rules (only admins, what each button does) are in admin.py. These
# functions do not check who is asking, so only admin.py calls them.


def _now() -> str:
    """The current time, in the form Supabase stores it."""
    return datetime.now(timezone.utc).isoformat()


def get_report(report_id: int) -> dict | None:
    """Return the report with this number, or None if there is none."""
    rows = _client().table("reports").select("*").eq("id", report_id).execute().data
    return rows[0] if rows else None


def open_reports() -> list[dict]:
    """Return every report no admin has handled yet, oldest first."""
    return (
        _client().table("reports").select("*").eq("status", "open")
        .order("created_at").order("id")
        .execute().data
    )


def close_reports(report_ids: list[int], status: str) -> None:
    """Give these open reports a new status ("blocked" or "dismissed") and the time."""
    if report_ids:
        (
            _client().table("reports").update({"status": status, "handled_at": _now()})
            .in_("id", list(report_ids)).eq("status", "open")
            .execute()
        )


def block_profile(profile_id: int) -> None:
    """Mark a student as blocked, from now on."""
    _client().table("profiles").update({"blocked_at": _now()}).eq("id", profile_id).execute()


def admin_delete_listing(listing_id: int) -> None:
    """Remove any listing, whoever the seller is. Its reports go with it."""
    _client().table("listings").delete().eq("id", listing_id).execute()


# --- Photos -------------------------------------------------------------------


def _upload(bucket: str, picture: bytes) -> str:
    """Store a JPEG or PNG picture in a bucket and return its new name."""
    is_png = picture.startswith(b"\x89PNG")
    path = f"{uuid.uuid4().hex}.{'png' if is_png else 'jpg'}"
    content_type = "image/png" if is_png else "image/jpeg"
    _client().storage.from_(bucket).upload(path, picture, {"content-type": content_type})
    return path


def _signed_url(bucket: str, path: str | None) -> str | None:
    """Return a link that shows the photo for one hour, or None without a photo.

    The photos are private. Only a link made here can show one, and it
    stops working after an hour.
    """
    if not path:
        return None
    return _client().storage.from_(bucket).create_signed_url(path, PHOTO_LINK_SECONDS)["signedUrl"]


def upload_photo(jpeg_bytes: bytes) -> str:
    """Store a profile photo and return the name it was stored under."""
    return _upload(PHOTO_BUCKET, jpeg_bytes)


def delete_photo(path: str) -> None:
    """Remove a stored profile photo."""
    _client().storage.from_(PHOTO_BUCKET).remove([path])


def photo_url(path: str | None) -> str | None:
    """Return a one-hour link to a profile photo, or None without a photo."""
    return _signed_url(PHOTO_BUCKET, path)


def upload_listing_photo(picture: bytes) -> str:
    """Store a listing photo and return the name it was stored under."""
    return _upload(LISTING_PHOTO_BUCKET, picture)


def delete_listing_photos(paths: list[str]) -> None:
    """Remove stored listing photos."""
    if paths:
        _client().storage.from_(LISTING_PHOTO_BUCKET).remove(list(paths))


def listing_photo_url(path: str | None) -> str | None:
    """Return a one-hour link to a listing photo, or None without a photo."""
    return _signed_url(LISTING_PHOTO_BUCKET, path)
