"""Database: the only file that talks to Supabase.

Supabase is the online service that stores our tables and photos. The
tables are created once with database_setup.sql.

The key this file uses may read and change everything in the database.
That is why it stays in .streamlit/secrets.toml, and why the pages decide
who may do what before they call a function from here: a page always
passes the email it got from the login, never one typed into a form.
"""

import threading
import time
import uuid
from datetime import date, datetime, timezone

import streamlit as st
from postgrest.exceptions import APIError
from supabase import Client, create_client

PHOTO_BUCKET = "profile-photos"
LISTING_PHOTO_BUCKET = "listing-photos"
PHOTO_LINK_SECONDS = 3600  # a photo link works for one hour
# A photo link is reused for 50 minutes, so a link we hand out still has
# at least 10 minutes left before it stops working.
PHOTO_LINK_REUSE_SECONDS = 50 * 60

# --- Speed --------------------------------------------------------------------
#
# Streamlit runs the whole page again on every click. Without help, every click
# would ask Supabase again for the same profile, the same listings and a new
# link for every photo, one request after another. So a few answers are kept
# for a short time (st.cache_data with "ttl", time to live, in seconds).
# Every function below that changes those rows empties the matching memory
# right away, so a change is never hidden behind an old answer.
PROFILE_MEMORY_SECONDS = 60
FEED_MEMORY_SECONDS = 30
FAVORITES_MEMORY_SECONDS = 60
# Only for the counts in the menu ("Sales (2)"). A request another student
# sends shows up in the count at most this many seconds later.
TO_DO_MEMORY_SECONDS = 20


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


@st.cache_data(ttl=PROFILE_MEMORY_SECONDS, show_spinner=False)
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
    get_profile.clear()
    return saved[0]


def accept_house_rules(email: str) -> None:
    """Remember that the student with this email agreed to the house rules (now)."""
    now = datetime.now(timezone.utc).isoformat()
    _client().table("profiles").update({"rules_accepted_at": now}).eq("email", email).execute()
    get_profile.clear()


# --- Listings -----------------------------------------------------------------
#
# The rules (who may change a listing, what a valid listing is) are in
# listings.py. The functions that change a listing also need the seller's
# profile number, so a listing can only ever be changed by its own seller.


def insert_listing(row: dict) -> dict:
    """Store a new listing and return it, with its new id."""
    stored = _client().table("listings").insert(row).execute().data[0]
    feed_listings.clear()
    return stored


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


@st.cache_data(ttl=FEED_MEMORY_SECONDS, show_spinner=False)
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


def update_listing(listing_id: int, seller_id: int, changes: dict,
                   only_if_status: str | None = None) -> bool:
    """Change a listing. Nothing happens if the listing belongs to someone else.

    With only_if_status, the database changes the listing only if it still has
    that status at that very moment (see "Changing a status safely" in deals.py).
    Returns True if a row was changed.
    """
    changes = {**changes, "updated_at": datetime.now(timezone.utc).isoformat()}
    query = (
        _client().table("listings").update(changes)
        .eq("id", listing_id).eq("seller_id", seller_id)
    )
    if only_if_status is not None:
        query = query.eq("status", only_if_status)
    changed = query.execute().data
    _listings_changed()
    return bool(changed)


def delete_listing(listing_id: int, seller_id: int) -> None:
    """Remove a listing. Nothing happens if the listing belongs to someone else."""
    _client().table("listings").delete().eq("id", listing_id).eq("seller_id", seller_id).execute()
    _listings_changed()
    live_deals_of.clear()  # its requests were deleted with it


def _listings_changed() -> None:
    """Forget the remembered feed and saved lists, so the change shows at once."""
    feed_listings.clear()
    favorite_listings.clear()


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
    _favorites_changed()


def remove_favorite(profile_id: int, listing_id: int) -> None:
    """Remove a saved listing."""
    (
        _client().table("favorites").delete()
        .eq("profile_id", profile_id).eq("listing_id", listing_id)
        .execute()
    )
    _favorites_changed()


def _favorites_changed() -> None:
    """Forget the remembered saved lists, so a save or unsave shows at once."""
    favorite_ids.clear()
    favorite_listings.clear()


@st.cache_data(ttl=FAVORITES_MEMORY_SECONDS, show_spinner=False)
def favorite_ids(profile_id: int) -> list[int]:
    """The ids of the listings this buyer saved, newest-saved first."""
    rows = (
        _client().table("favorites").select("listing_id")
        .eq("profile_id", profile_id).order("id", desc=True)
        .execute().data
    )
    return [row["listing_id"] for row in rows]


@st.cache_data(ttl=FAVORITES_MEMORY_SECONDS, show_spinner=False)
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


# --- Buying (purchase requests) -----------------------------------------------
#
# A buyer asks to buy a listing; the seller accepts; then both sides confirm the
# hand-over. The rules (who may do what) live in deals.py; here we only store.


def insert_request(row: dict) -> dict:
    """Store a new purchase request and return it, with its new id."""
    stored = _client().table("purchase_requests").insert(row).execute().data[0]
    live_deals_of.clear()
    return stored


def get_request(request_id: int) -> dict | None:
    """Return the request with this number, or None if there is none."""
    rows = _client().table("purchase_requests").select("*").eq("id", request_id).execute().data
    return rows[0] if rows else None


def live_request(buyer_id: int, listing_id: int) -> dict | None:
    """This buyer's requested-or-accepted request for this listing, or None."""
    rows = (
        _client().table("purchase_requests").select("*")
        .eq("buyer_id", buyer_id).eq("listing_id", listing_id)
        .in_("status", ["requested", "accepted"]).limit(1)
        .execute().data
    )
    return rows[0] if rows else None


def requests_for_listing(listing_id: int, statuses: list[str]) -> list[dict]:
    """Requests on a listing with one of these statuses, oldest first (a fair queue)."""
    return (
        _client().table("purchase_requests").select("*")
        .eq("listing_id", listing_id).in_("status", statuses)
        .order("created_at").order("id")
        .execute().data
    )


def requests_by_buyer(buyer_id: int, statuses: list[str]) -> list[dict]:
    """A buyer's requests with one of these statuses, newest first."""
    return (
        _client().table("purchase_requests").select("*")
        .eq("buyer_id", buyer_id).in_("status", statuses)
        .order("created_at", desc=True).order("id", desc=True)
        .execute().data
    )


def requests_for_seller(seller_id: int, statuses: list[str]) -> list[dict]:
    """Requests on any of this seller's listings, oldest first, in ONE request.

    "listings!inner(...)" attaches each request's listing (as row["listings"])
    and keeps only the requests whose listing belongs to this seller.
    """
    return (
        _client().table("purchase_requests")
        .select("*, listings!inner(seller_id, title, price_cents)")
        .eq("listings.seller_id", seller_id).in_("status", statuses)
        .order("created_at").order("id")
        .execute().data
    )


def disputed_returns() -> list[dict]:
    """Deals where the seller said the item came back in a worse condition, oldest first.

    Each has its listing attached as row["listings"]. Only admin.py uses this.
    """
    return (
        _client().table("purchase_requests")
        .select("*, listings!inner(seller_id, title, price_cents)")
        .eq("status", "accepted").not_.is_("return_disputed_at", "null")
        .order("created_at").order("id")
        .execute().data
    )


@st.cache_data(ttl=TO_DO_MEMORY_SECONDS, show_spinner=False)
def live_deals_of(profile_id: int) -> dict[str, list[dict]]:
    """This student's live deals, for the counts in the menu (remembered briefly).

    {"selling": requests on their listings, "buying": their own requests}.
    Only for showing counts: the rules in deals.py always read fresh rows.
    """
    live = ["requested", "accepted"]
    return {"selling": requests_for_seller(profile_id, live),
            "buying": requests_by_buyer(profile_id, live)}


def update_request(request_id: int, changes: dict,
                   only_if_status: str | None = None) -> bool:
    """Change a purchase request (status or a confirmation time).

    With only_if_status, the database changes it only if it still has that
    status at that very moment. Returns True if a row was changed.
    """
    query = _client().table("purchase_requests").update(changes).eq("id", request_id)
    if only_if_status is not None:
        query = query.eq("status", only_if_status)
    changed = query.execute().data
    live_deals_of.clear()
    return bool(changed)


def names_of(profile_ids: list[int]) -> dict[int, str]:
    """{profile id: name} for many students, in one request."""
    wanted = sorted({pid for pid in profile_ids if pid is not None})
    if not wanted:
        return {}
    rows = _client().table("profiles").select("id, name").in_("id", wanted).execute().data
    return {row["id"]: row["name"] for row in rows}


# --- Reviews ------------------------------------------------------------------
#
# After a completed deal, buyer and seller each rate the other once (1 to 5 stars, plus optional feedback).
# The rules are in reviews.py; here we only store.


def insert_review(row: dict) -> dict:
    """Store a new review and return it."""
    return _client().table("reviews").insert(row).execute().data[0]


def reviews_about(profile_id: int) -> list[dict]:
    """Every review other students left about this student."""
    return _client().table("reviews").select("*").eq("reviewee_id", profile_id).execute().data


def reviews_by(reviewer_id: int) -> list[dict]:
    """Every review this student left."""
    return _client().table("reviews").select("*").eq("reviewer_id", reviewer_id).execute().data


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
    get_profile.clear()
    _listings_changed()  # the blocked student's listings leave the feed


def admin_delete_listing(listing_id: int) -> None:
    """Remove any listing, whoever the seller is. Its reports go with it."""
    _client().table("listings").delete().eq("id", listing_id).execute()
    _listings_changed()
    live_deals_of.clear()  # its requests were deleted with it


# --- Photos -------------------------------------------------------------------


def _upload(bucket: str, picture: bytes) -> str:
    """Store a JPEG or PNG picture in a bucket and return its new name."""
    is_png = picture.startswith(b"\x89PNG")
    path = f"{uuid.uuid4().hex}.{'png' if is_png else 'jpg'}"
    content_type = "image/png" if is_png else "image/jpeg"
    _client().storage.from_(bucket).upload(path, picture, {"content-type": content_type})
    return path


@st.cache_resource
def _photo_links() -> dict:
    """Photo links made earlier, shared by everyone using the app.

    Maps (bucket, photo name) to (link, time until which we reuse it).
    """
    return {}


_photo_links_lock = threading.Lock()


def _signed_urls(bucket: str, paths: list[str]) -> dict[str, str]:
    """Return {photo name: link} for these photos, asking Supabase at most once.

    The photos are private. Only a link made here can show one, and it
    stops working after an hour. Links made in the last 50 minutes are
    reused; all missing links are made together in a single request.
    """
    links = _photo_links()
    now = time.time()
    wanted = {path for path in paths if path}
    with _photo_links_lock:
        missing = [path for path in wanted if links.get((bucket, path), (None, 0))[1] < now]
    if missing:
        made = _client().storage.from_(bucket).create_signed_urls(missing, PHOTO_LINK_SECONDS)
        with _photo_links_lock:
            for item in made:
                if item.get("signedURL") and not item.get("error"):
                    links[(bucket, item["path"])] = (item["signedURL"],
                                                     now + PHOTO_LINK_REUSE_SECONDS)
    with _photo_links_lock:
        return {path: links[(bucket, path)][0] for path in wanted if (bucket, path) in links}


def _signed_url(bucket: str, path: str | None) -> str | None:
    """Return a link that shows one photo for up to an hour, or None without a photo."""
    return _signed_urls(bucket, [path]).get(path) if path else None


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


def listing_photo_urls(paths: list[str]) -> dict[str, str]:
    """Return {photo name: link} for many listing photos, in one request at most."""
    return _signed_urls(LISTING_PHOTO_BUCKET, paths)


# --- Messaging transport ------------------------------------------------------
# Internal helpers for messaging_repository.py. That module authenticates the
# current Streamlit user before calling these; pages must use the repository.
# No global caching of private rows or per-user changes to the shared client.


def messaging_actor_profile(email: str) -> dict | None:
    """Uncached authorization state; blocking must apply on the next operation.

    Kept separate from the profile-display cache used by the rest of the app.
    """
    rows = (_client().table("profiles")
            .select("id,email,blocked_at,rules_accepted_at")
            .eq("email", email).limit(1).execute().data)
    return rows[0] if rows else None


def messaging_conversation(conversation_id: str, actor_id: int) -> dict | None:
    rows = (_client().table("conversations").select("*")
            .eq("id", conversation_id)
            .or_(f"buyer_id.eq.{actor_id},seller_id.eq.{actor_id}")
            .limit(1).execute().data)
    return rows[0] if rows else None


def messaging_conversations(actor_id: int) -> list[dict]:
    # Read in bounded batches so a recently active, older conversation isn't
    # excluded before the repository sorts by latest message activity.
    rows = []
    while True:
        batch = (_client().table("conversations").select("*")
                 .or_(f"buyer_id.eq.{actor_id},seller_id.eq.{actor_id}")
                 .order("created_at", desc=True).order("id", desc=True)
                 .range(len(rows), len(rows) + 99).execute().data)
        rows.extend(batch)
        if len(batch) < 100:
            return rows


def messaging_messages(conversation_id: str, limit: int, offset: int) -> list[dict]:
    return (_client().table("messages").select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=True).order("id", desc=True)
            .range(offset, offset + limit - 1).execute().data)


def messaging_insert_message(payload: dict) -> dict:
    try:
        return _client().table("messages").insert(payload).execute().data[0]
    except APIError as error:
        if error.code != "23505":
            raise
        rows = (_client().table("messages").select("*")
                .eq("conversation_id", payload["conversation_id"])
                .eq("client_message_id", payload["client_message_id"])
                .limit(1).execute().data)
        if not rows:
            raise
        return rows[0]  # Repository checks sender/body before accepting a retry.


def messaging_insert_conversation(payload: dict) -> dict:
    try:
        return _client().table("conversations").insert(payload).execute().data[0]
    except APIError as error:
        if error.code != "23505":
            raise
        rows = (_client().table("conversations").select("*")
                .eq("original_listing_id", payload["listing_id"])
                .eq("buyer_id", payload["buyer_id"]).limit(1).execute().data)
        if not rows:
            raise
        return rows[0]


def messaging_conversation_for_listing(listing_id: int, buyer_id: int) -> dict | None:
    rows = (_client().table("conversations").select("*")
            .eq("original_listing_id", listing_id).eq("buyer_id", buyer_id)
            .limit(1).execute().data)
    return rows[0] if rows else None


# --- Wallet (Nova credits, see wallet.py) ---------------------------------------
# The rules are in wallet.py. The two steps that must never run twice or spend
# the same credits twice (hold, settle) are database functions in
# database_setup.sql, so the check and the change happen in one step.


def wallet_entries_of(profile_id: int) -> list[dict]:
    """Every wallet line of one student, newest first."""
    return (
        _client().table("wallet_entries").select("*").eq("profile_id", profile_id)
        .order("created_at", desc=True).order("id", desc=True)
        .execute().data
    )


def wallet_add_entry(row: dict) -> dict:
    """Store one wallet line (only used for added credits)."""
    return _client().table("wallet_entries").insert(row).execute().data[0]


def wallet_hold(profile_id: int, request_id: int, amount_cents: int, note: str | None) -> bool:
    """Hold money for a deal if the balance is enough (one step, in the database)."""
    return bool(_client().rpc("wallet_hold", {
        "p_profile": profile_id, "p_request": request_id,
        "p_amount": amount_cents, "p_note": note,
    }).execute().data)


def wallet_settle(request_id: int, kind: str, profile_id: int) -> bool:
    """Release a deal's held money to the seller, or refund it to the buyer (once)."""
    return bool(_client().rpc("wallet_settle", {
        "p_request": request_id, "p_kind": kind, "p_profile": profile_id,
    }).execute().data)


def messaging_offers(conversation_id: str, limit: int, offset: int) -> list[dict]:
    return (_client().table("offers").select("*").eq("conversation_id", conversation_id)
            .order("created_at", desc=True).order("id", desc=True)
            .range(offset, offset + limit - 1).execute().data)


def messaging_offer_action(payload: dict) -> dict:
    """One atomic database transaction; only the trusted repository calls this."""
    return _client().rpc("messaging_offer_action", payload).execute().data
