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


def _attach_seller_names(rows: list[dict]) -> list[dict]:
    """Add a 'seller_name' to each listing by looking the sellers up in profiles.
    One extra query for the whole batch, so cards can show who is selling."""
    seller_ids = sorted({row["seller_id"] for row in rows})
    names = {}
    if seller_ids:
        people = _client().table("profiles").select("id, name").in_("id", seller_ids).execute().data
        names = {person["id"]: person["name"] for person in people}
    for row in rows:
        row["seller_name"] = names.get(row["seller_id"], "A student")
    return rows


def get_active_listings(profile_id: int) -> list[dict]:
    """The available listings of one student (used by their public profile)."""
    return (
        _client().table("listings").select("*")
        .eq("seller_id", profile_id).eq("status", "available")
        .order("created_at", desc=True).execute().data
    )


def list_listings(include_sold: bool = False) -> list[dict]:
    """Every listing, newest first, each with the seller's name. Searching,
    filtering and sorting are done in listings.py so they can be tested without
    the database."""
    query = _client().table("listings").select("*")
    if not include_sold:
        query = query.eq("status", "available")
    rows = query.order("created_at", desc=True).execute().data
    return _attach_seller_names(rows)


def get_listing(listing_id: int) -> dict | None:
    """One listing with its seller's name, or None if it does not exist."""
    rows = _client().table("listings").select("*").eq("id", listing_id).execute().data
    return _attach_seller_names(rows)[0] if rows else None


def create_listing(seller_id: int, title: str, description: str,
                   price: float, category: str) -> dict:
    """Post a new item for sale and return the stored row."""
    row = {
        "seller_id": seller_id,
        "title": title,
        "description": description,
        "price": float(price),
        "category": category,
    }
    return _client().table("listings").insert(row).execute().data[0]


def mark_listing_sold(listing_id: int) -> None:
    _client().table("listings").update({"status": "sold"}).eq("id", listing_id).execute()


def delete_listing(listing_id: int) -> None:
    _client().table("listings").delete().eq("id", listing_id).execute()


# --- Favourites (a buyer's saved listings) ------------------------------------


def add_favorite(profile_id: int, listing_id: int) -> None:
    """Save a listing for a student. Saving twice keeps a single row."""
    _client().table("favorites").upsert(
        {"profile_id": profile_id, "listing_id": listing_id},
        on_conflict="profile_id,listing_id",
    ).execute()


def remove_favorite(profile_id: int, listing_id: int) -> None:
    (
        _client().table("favorites").delete()
        .eq("profile_id", profile_id).eq("listing_id", listing_id).execute()
    )


def favorite_listing_ids(profile_id: int) -> set[int]:
    """The ids of the listings this student has saved."""
    rows = (
        _client().table("favorites").select("listing_id")
        .eq("profile_id", profile_id).execute().data
    )
    return {row["listing_id"] for row in rows}


def list_favorite_listings(profile_id: int) -> list[dict]:
    """The full saved listings for this student, each with the seller's name."""
    ids = favorite_listing_ids(profile_id)
    if not ids:
        return []
    rows = _client().table("listings").select("*").in_("id", list(ids)).execute().data
    return _attach_seller_names(rows)


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
