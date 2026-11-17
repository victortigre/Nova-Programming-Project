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


def feed_listings(limit: int, offset: int) -> list[dict]:
    """Return the listings buyers may see (not sold ones), newest first."""
    return (
        _client().table("listings").select("*").neq("status", "sold")
        .order("created_at", desc=True).order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute().data
    )


def get_active_listings(profile_id: int) -> list[dict]:
    """Return the active listings of one student, newest first."""
    return (
        _client().table("listings").select("*")
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
