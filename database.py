"""Database: the only file that talks to Supabase.

Supabase is the online service that stores our tables and photos. The
tables are created once with database_setup.sql.

The key this file uses may read and change everything in the database.
That is why it stays in .streamlit/secrets.toml, and why the pages decide
who may do what before they call a function from here: a page always
passes the email it got from the login, never one typed into a form.
"""

import uuid
from datetime import date

import streamlit as st
from supabase import Client, create_client

PHOTO_BUCKET = "profile-photos"
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


def get_active_listings(profile_id: int) -> list[dict]:
    """Return the active listings of one student.

    Not built yet: there is no listings table. Until the listings part of
    the project fills this in, every student has no listings. The public
    profile page shows a "title" and a "price" for each listing returned.
    """
    return []


# --- Profile photos -----------------------------------------------------------


def upload_photo(jpeg_bytes: bytes) -> str:
    """Store a photo and return the name it was stored under."""
    path = f"{uuid.uuid4().hex}.jpg"
    _client().storage.from_(PHOTO_BUCKET).upload(
        path, jpeg_bytes, {"content-type": "image/jpeg"}
    )
    return path


def delete_photo(path: str) -> None:
    """Remove a stored photo."""
    _client().storage.from_(PHOTO_BUCKET).remove([path])


def photo_url(path: str | None) -> str | None:
    """Return a link that shows the photo for one hour, or None without a photo.

    The photos are private. Only a link made here can show one, and it
    stops working after an hour.
    """
    if not path:
        return None
    link = _client().storage.from_(PHOTO_BUCKET).create_signed_url(path, PHOTO_LINK_SECONDS)
    return link["signedUrl"]
