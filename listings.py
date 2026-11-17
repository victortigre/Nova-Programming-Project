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
* The seller must be a Nova address with a profile. The pages pass the email
  from the login (accounts.verified_nova_email), never one typed into a form.
* All input is checked here, so bad data can't get in by going around a form.

Storage: this file never talks to Supabase itself. Every function takes `db`
first: the place where listings are stored. The pages pass the `database`
module (the real Supabase storage). The tests pass a pretend database that
lives in memory (tests/fake_database.py), so they run without internet.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from accounts import nova_email
from photos import PhotoError, check_photo_count, prepare_photos

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


class ListingError(ValueError):
    """The input breaks one or more rules. `errors` lists every problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


class NotAllowed(PermissionError):
    """The person isn't allowed to do this (for example, not the seller)."""


class NotFound(LookupError):
    """The listing doesn't exist (any more)."""


# --- money ----------------------------------------------------------------------

def euros_to_cents(euros) -> int:
    """12.5 -> 1250. Done with Decimal so 0.1 + 0.2 doesn't become 0.30000000000000004."""
    return int((Decimal(str(euros)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_price(cents: int) -> str:
    """1250 -> '€12.50', 0 -> 'Free'."""
    return "Free" if cents == 0 else f"€{cents / 100:,.2f}"


# --- showing text -----------------------------------------------------------------

def plain_text(text: str) -> str:
    """Escape Markdown, so text a student typed (like a title) shows exactly as typed.

    '[click](http://x)' -> '\\[click\\]\\(http\\:...' : no link, no formatting.
    A backslash is put before every character Markdown treats as special.
    """
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>~<$:])", r"\\\1", text)


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


def _fields(*, title, description, free, price_cents, category, condition,
            pickup_area) -> dict:
    """The checked fields, tidied, in the shape they are stored in."""
    return {
        "title": title.strip(),
        "description": description.strip(),
        "price_cents": 0 if free else price_cents,
        "category": category,
        "condition": condition,
        "pickup_area": pickup_area,
    }


def _seller_profile(db, email: str) -> dict:
    """The profile of the person selling. Every listing belongs to a profile."""
    seller = nova_email({"email": email})
    if seller is None:
        raise NotAllowed("Only @novasbe.pt accounts can sell.")
    profile = db.get_profile(seller)
    if profile is None:
        raise NotAllowed("Fill in your profile before you sell something.")
    return profile


def _photos_or_errors(photos: list[bytes]) -> tuple[list[bytes], list[str]]:
    try:
        return prepare_photos(photos), []
    except PhotoError as exc:
        return [], exc.errors


# --- reading ----------------------------------------------------------------------

def get_listing(db, listing_id: int) -> dict | None:
    return db.get_listing(listing_id)


def get_photos(db, listing_id: int) -> list[str]:
    """The stored names of the listing's photos, in display order (cover first)."""
    listing = db.get_listing(listing_id)
    return list(listing["photo_paths"]) if listing else []


def my_listings(db, seller_email: str) -> dict[str, list[dict]]:
    """{'active': [...], 'reserved': [...], 'sold': [...]}, newest first."""
    groups = {status: [] for status in STATUSES}
    for listing in db.listings_of_seller(_seller_profile(db, seller_email)["id"]):
        groups[listing["status"]].append(listing)
    return groups


def feed_listings(db, limit: int = 20, offset: int = 0) -> list[dict]:
    """What buyers may see: active and reserved listings, newest first. Never sold ones."""
    return db.feed_listings(limit, offset)


# --- changing -------------------------------------------------------------------

def create_listing(db, seller_email: str, *, title: str, description: str,
                   free: bool, price_cents: int, category: str, condition: str,
                   pickup_area: str, photos: list[bytes]) -> int:
    """Publish a new listing. Returns its id. Raises ListingError listing every problem."""
    seller = _seller_profile(db, seller_email)
    if seller.get("blocked_at"):  # an admin blocked this student (see admin.py)
        raise NotAllowed("Your account has been blocked, so you cannot sell.")
    fields = dict(title=title, description=description, free=free,
                  price_cents=price_cents, category=category,
                  condition=condition, pickup_area=pickup_area)
    errors = check_listing(**fields)
    count_errors = check_photo_count(len(photos))
    errors += count_errors
    if not count_errors:
        photos, photo_errors = _photos_or_errors(photos)
        errors += photo_errors
    if errors:
        raise ListingError(errors)

    paths = [db.upload_listing_photo(data) for data in photos]
    row = {**_fields(**fields), "seller_id": seller["id"], "photo_paths": paths}
    try:
        listing = db.insert_listing(row)
    except Exception:
        db.delete_listing_photos(paths)  # don't leave photos without a listing
        raise
    return listing["id"]


def _own_listing(db, listing_id: int, seller_email: str) -> tuple[dict, dict]:
    """(listing, seller profile), if this person is its seller. Otherwise NotFound / NotAllowed."""
    seller = _seller_profile(db, seller_email)
    listing = db.get_listing(listing_id)
    if listing is None:
        raise NotFound("This listing doesn't exist any more.")
    if listing["seller_id"] != seller["id"]:
        raise NotAllowed("Only the seller can change this listing.")
    return listing, seller


def update_listing(db, listing_id: int, seller_email: str, *, title: str, description: str,
                   free: bool, price_cents: int, category: str, condition: str,
                   pickup_area: str, keep_photo_paths: list[str] | None = None,
                   new_photos: list[bytes] = ()) -> None:
    """Edit your own listing.

    keep_photo_paths: the current photos to keep, in the order to show them
                      (the first one becomes the cover). None = keep all of them.
    new_photos:       extra photos to add after the kept ones.
    """
    listing, seller = _own_listing(db, listing_id, seller_email)
    current = list(listing["photo_paths"])
    if keep_photo_paths is None:
        keep_photo_paths = current
    if any(path not in current for path in keep_photo_paths):
        raise NotAllowed("A photo you tried to keep doesn't belong to this listing.")

    fields = dict(title=title, description=description, free=free,
                  price_cents=price_cents, category=category,
                  condition=condition, pickup_area=pickup_area)
    errors = check_listing(**fields)
    new_photos = list(new_photos)
    count_errors = check_photo_count(len(keep_photo_paths) + len(new_photos))
    errors += count_errors
    if new_photos and not count_errors:
        new_photos, photo_errors = _photos_or_errors(new_photos)
        errors += photo_errors
    if errors:
        raise ListingError(errors)

    new_paths = [db.upload_listing_photo(data) for data in new_photos]
    changes = {**_fields(**fields), "photo_paths": list(keep_photo_paths) + new_paths}
    db.update_listing(listing_id, seller["id"], changes)

    removed = [path for path in current if path not in keep_photo_paths]
    if removed:
        db.delete_listing_photos(removed)


def delete_listing(db, listing_id: int, seller_email: str) -> None:
    """Remove the listing and its photos for good."""
    listing, seller = _own_listing(db, listing_id, seller_email)
    db.delete_listing(listing_id, seller["id"])
    if listing["photo_paths"]:
        db.delete_listing_photos(listing["photo_paths"])


# Which status changes make sense, and what to call them in error messages.
_ALLOWED_MOVES = {
    RESERVED: ({ACTIVE}, "Only an active listing can be marked as reserved."),
    SOLD: ({ACTIVE, RESERVED}, "This listing is already sold."),
    ACTIVE: ({RESERVED, SOLD}, "This listing is already active."),
}


def _move(db, listing_id: int, seller_email: str, new_status: str) -> None:
    listing, seller = _own_listing(db, listing_id, seller_email)
    allowed_from, message = _ALLOWED_MOVES[new_status]
    if listing["status"] not in allowed_from:
        raise ListingError([message])
    db.update_listing(listing_id, seller["id"], {"status": new_status})


def mark_reserved(db, listing_id: int, seller_email: str) -> None:
    _move(db, listing_id, seller_email, RESERVED)


def mark_sold(db, listing_id: int, seller_email: str) -> None:
    _move(db, listing_id, seller_email, SOLD)


def relist(db, listing_id: int, seller_email: str) -> None:
    _move(db, listing_id, seller_email, ACTIVE)
