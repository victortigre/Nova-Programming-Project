"""Listings: everything a seller does with the items they offer.

Features (area 2 of the MVP):
    create_listing   title, description, price or free, category, condition,
                     pickup area, 1-5 photos
    update_listing   change any field, keep/remove photos, add new ones
    delete_listing   removes it from the marketplace
    mark_reserved    stays visible with a "Reserved" badge
    mark_sold        disappears from the feed and search
    relist           a reserved or sold item goes back to active
    my_listings      own listings grouped as active, reserved, sold

For the browse/search area: feed_listings() returns what buyers may see
(sold items are never included).

Rules that keep this safe:
* Only the seller can change or delete their listing. This is checked HERE,
  where the change happens, not only by hiding buttons on the page.
* The seller must be a Nova address (accounts.nova_email). The pages also
  require the address to be verified before calling these functions.
* All input is checked here, so bad data can't get in by going around a form.
* SQL always uses ? placeholders, never text built from user input.

Storage: a SQLite file (db.sqlite3 by default, already ignored by git).
Every function takes the database connection first, so the tests can use a
throw-away database in memory.
"""

import os
import sqlite3
from decimal import ROUND_HALF_UP, Decimal

from accounts import nova_email
from photos import PhotoError, check_photo_count, prepare_photos

DB_PATH = os.environ.get("NOVA_DB_PATH", "db.sqlite3")

CATEGORIES = [
    "Textbooks",
    "Calculators & electronics",
    "Furniture",
    "Kitchen",
    "Clothing",
    "Sports",
    "Other",
]
CONDITIONS = ["New", "Like new", "Good", "Fair"]
PICKUP_AREAS = ["Nova SBE campus", "Carcavelos", "Cascais", "Oeiras", "Lisbon centre", "Other"]

ACTIVE, RESERVED, SOLD = "active", "reserved", "sold"
STATUSES = [ACTIVE, RESERVED, SOLD]

MAX_PRICE_CENTS = 1_000_000  # €10,000

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_email TEXT NOT NULL,
    seller_name  TEXT NOT NULL,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    price_cents  INTEGER NOT NULL CHECK (price_cents >= 0),  -- 0 = free
    category     TEXT NOT NULL,
    condition    TEXT NOT NULL,
    pickup_area  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active', 'reserved', 'sold')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS listing_photos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,  -- 0 is the cover photo
    data       BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_seller ON listings(seller_email);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status, created_at);
"""

# Each listing row also gets its first photo, for cards and lists.
_SELECT = """
    SELECT l.*,
           (SELECT p.data FROM listing_photos p
            WHERE p.listing_id = l.id ORDER BY p.position LIMIT 1) AS cover
    FROM listings l
"""


class ListingError(ValueError):
    """The input breaks one or more rules. `errors` lists every problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


class NotAllowed(PermissionError):
    """The person isn't allowed to do this (for example, not the seller)."""


class NotFound(LookupError):
    """The listing doesn't exist (any more)."""


# --- database -----------------------------------------------------------------

def connect(path: str = DB_PATH) -> sqlite3.Connection:
    """Open the database and create the tables if they don't exist yet."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# --- money ----------------------------------------------------------------------

def euros_to_cents(euros) -> int:
    """12.5 -> 1250. Done with Decimal so 0.1 + 0.2 doesn't become 0.30000000000000004."""
    return int((Decimal(str(euros)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_price(cents: int) -> str:
    """1250 -> '€12.50', 0 -> 'Free'."""
    return "Free" if cents == 0 else f"€{cents / 100:,.2f}"


# --- input rules ------------------------------------------------------------------

def _text(value, label: str, min_len: int, max_len: int) -> list[str]:
    value = (value or "").strip()
    if len(value) < min_len:
        return [f"{label} must be at least {min_len} characters."]
    if len(value) > max_len:
        return [f"{label} must be at most {max_len} characters."]
    return []


def check_offer(*, free: bool, price_cents: int) -> list[str]:
    """'Sell for a price' needs a real price; 'Give it away for free' needs none."""
    if free:
        return []
    if not isinstance(price_cents, int) or isinstance(price_cents, bool):
        return ["Price must be a number."]
    if price_cents <= 0:
        return ["Enter a price, or choose “Give it away for free”."]
    if price_cents > MAX_PRICE_CENTS:
        return [f"Price can't be more than €{MAX_PRICE_CENTS // 100:,}."]
    return []


def check_listing(*, title, description, free, price_cents, category, condition,
                  pickup_area) -> list[str]:
    """Every problem with the listing's fields (empty list = all good)."""
    errors = _text(title, "Title", 3, 80) + _text(description, "Description", 10, 2000)
    errors += check_offer(free=free, price_cents=price_cents)
    if category not in CATEGORIES:
        errors.append("Choose a category from the list.")
    if condition not in CONDITIONS:
        errors.append("Choose a condition from the list.")
    if pickup_area not in PICKUP_AREAS:
        errors.append("Choose a pickup area from the list.")
    return errors


def _seller(email: str) -> str:
    seller = nova_email({"email": email})
    if seller is None:
        raise NotAllowed("Only @novasbe.pt accounts can sell.")
    return seller


def _photos_or_errors(photos: list[bytes]) -> tuple[list[bytes], list[str]]:
    try:
        return prepare_photos(photos), []
    except PhotoError as exc:
        return [], exc.errors


# --- reading ----------------------------------------------------------------------

def get_listing(conn, listing_id: int) -> dict | None:
    row = conn.execute(_SELECT + " WHERE l.id = ?", (listing_id,)).fetchone()
    return dict(row) if row else None


def get_photos(conn, listing_id: int) -> list[dict]:
    """[{'id': ..., 'data': bytes}, ...] in display order (cover first)."""
    rows = conn.execute(
        "SELECT id, data FROM listing_photos WHERE listing_id = ? ORDER BY position",
        (listing_id,),
    )
    return [dict(r) for r in rows]


def my_listings(conn, seller_email: str) -> dict[str, list[dict]]:
    """{'active': [...], 'reserved': [...], 'sold': [...]}, newest first."""
    groups = {status: [] for status in STATUSES}
    rows = conn.execute(
        _SELECT + " WHERE l.seller_email = ? ORDER BY l.created_at DESC, l.id DESC",
        (_seller(seller_email),),
    )
    for row in rows:
        groups[row["status"]].append(dict(row))
    return groups


def feed_listings(conn, limit: int = 20, offset: int = 0) -> list[dict]:
    """What buyers may see: active and reserved listings, newest first. Never sold ones."""
    rows = conn.execute(
        _SELECT + " WHERE l.status != 'sold' ORDER BY l.created_at DESC, l.id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return [dict(r) for r in rows]


# --- changing -------------------------------------------------------------------

def create_listing(conn, seller_email: str, seller_name: str, *, title: str, description: str,
                   free: bool, price_cents: int, category: str, condition: str,
                   pickup_area: str, photos: list[bytes]) -> int:
    """Publish a new listing. Returns its id. Raises ListingError listing every problem."""
    seller = _seller(seller_email)
    errors = check_listing(title=title, description=description, free=free,
                           price_cents=price_cents, category=category,
                           condition=condition, pickup_area=pickup_area)
    count_errors = check_photo_count(len(photos))
    errors += count_errors
    if not count_errors:
        photos, photo_errors = _photos_or_errors(photos)
        errors += photo_errors
    if errors:
        raise ListingError(errors)

    cur = conn.execute(
        "INSERT INTO listings (seller_email, seller_name, title, description, price_cents, "
        "category, condition, pickup_area) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (seller, (seller_name or seller).strip(), title.strip(), description.strip(),
         0 if free else price_cents, category, condition, pickup_area),
    )
    _save_photos(conn, cur.lastrowid, photos)
    conn.commit()
    return cur.lastrowid


def _save_photos(conn, listing_id: int, photos: list[bytes]) -> None:
    conn.executemany(
        "INSERT INTO listing_photos (listing_id, position, data) VALUES (?, ?, ?)",
        [(listing_id, position, data) for position, data in enumerate(photos)],
    )


def _own_listing(conn, listing_id: int, seller_email: str) -> dict:
    """The listing, if this person is its seller. Otherwise NotFound / NotAllowed."""
    listing = get_listing(conn, listing_id)
    if listing is None:
        raise NotFound("This listing doesn't exist any more.")
    if listing["seller_email"] != _seller(seller_email):
        raise NotAllowed("Only the seller can change this listing.")
    return listing


def update_listing(conn, listing_id: int, seller_email: str, *, title: str, description: str,
                   free: bool, price_cents: int, category: str, condition: str,
                   pickup_area: str, keep_photo_ids: list[int] | None = None,
                   new_photos: list[bytes] = ()) -> None:
    """Edit your own listing.

    keep_photo_ids: ids of the current photos to keep, in the order to show them
                    (the first one becomes the cover). None = keep all of them.
    new_photos:     extra photos to add after the kept ones.
    """
    _own_listing(conn, listing_id, seller_email)
    current = {p["id"]: p["data"] for p in get_photos(conn, listing_id)}
    if keep_photo_ids is None:
        keep_photo_ids = list(current)
    if any(pid not in current for pid in keep_photo_ids):
        raise NotAllowed("A photo you tried to keep doesn't belong to this listing.")

    errors = check_listing(title=title, description=description, free=free,
                           price_cents=price_cents, category=category,
                           condition=condition, pickup_area=pickup_area)
    new_photos = list(new_photos)
    count_errors = check_photo_count(len(keep_photo_ids) + len(new_photos))
    errors += count_errors
    if new_photos and not count_errors:
        new_photos, photo_errors = _photos_or_errors(new_photos)
        errors += photo_errors
    if errors:
        raise ListingError(errors)

    conn.execute(
        "UPDATE listings SET title = ?, description = ?, price_cents = ?, category = ?, "
        "condition = ?, pickup_area = ?, updated_at = datetime('now') WHERE id = ?",
        (title.strip(), description.strip(), 0 if free else price_cents, category,
         condition, pickup_area, listing_id),
    )
    final = [current[pid] for pid in keep_photo_ids] + new_photos
    conn.execute("DELETE FROM listing_photos WHERE listing_id = ?", (listing_id,))
    _save_photos(conn, listing_id, final)
    conn.commit()


def delete_listing(conn, listing_id: int, seller_email: str) -> None:
    """Remove the listing and its photos for good."""
    _own_listing(conn, listing_id, seller_email)
    conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    conn.commit()


# Which status changes make sense, and what to call them in error messages.
_ALLOWED_MOVES = {
    RESERVED: ({ACTIVE}, "Only an active listing can be marked as reserved."),
    SOLD: ({ACTIVE, RESERVED}, "This listing is already sold."),
    ACTIVE: ({RESERVED, SOLD}, "This listing is already active."),
}


def _move(conn, listing_id: int, seller_email: str, new_status: str) -> None:
    listing = _own_listing(conn, listing_id, seller_email)
    allowed_from, message = _ALLOWED_MOVES[new_status]
    if listing["status"] not in allowed_from:
        raise ListingError([message])
    conn.execute(
        "UPDATE listings SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (new_status, listing_id),
    )
    conn.commit()


def mark_reserved(conn, listing_id: int, seller_email: str) -> None:
    _move(conn, listing_id, seller_email, RESERVED)


def mark_sold(conn, listing_id: int, seller_email: str) -> None:
    _move(conn, listing_id, seller_email, SOLD)


def relist(conn, listing_id: int, seller_email: str) -> None:
    _move(conn, listing_id, seller_email, ACTIVE)
