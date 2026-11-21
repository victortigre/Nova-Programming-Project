"""Listings: everything a seller does with the items they offer.

Features (area 2 of the MVP):
    create_listing   title, description, price or free, category, condition,
                     pickup area, 1-5 photos. Every field is required; choosing
                     "Other" as category or pickup area requires typing what it is.
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
from datetime import date
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
CONDITIONS = ["Brand New", "Like New", "Good", "Fair"]
PICKUP_AREAS = ["Nova SBE campus", "Carcavelos", "Cascais", "Oeiras", "Lisbon centre", "Other"]

OTHER = "Other"  # choosing this in Category or Pickup area means typing what it is
MAX_OTHER_LENGTH = 40

ACTIVE, RESERVED, SOLD = "active", "reserved", "sold"
STATUSES = [ACTIVE, RESERVED, SOLD]

MAX_PRICE_CENTS = 100_000  # €1,000: the highest price a listing can have


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


def parse_price(text) -> int | None:
    """What the seller typed in the price box, in cents. None if the box is empty.

    Accepts the ways people write prices: '15', '15,50', '15.50', '€15', '15 €'.
    Raises ValueError for anything that isn't a price, like 'abc' or '1,2,3'.
    """
    cleaned = str(text or "").replace("€", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        return None
    if cleaned.count(".") > 1 or not cleaned.replace(".", "").isdigit():
        raise ValueError("Price must be a number, like 15 or 15,50.")
    return euros_to_cents(cleaned)


def price_text(cents: int | None) -> str:
    """1550 -> '15.50', for putting a price back in the price box."""
    return "" if cents is None else f"{cents / 100:.2f}"


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


def check_offer(*, free: bool | None, price_cents: int | None) -> list[str]:
    """The seller must choose: 'Sell for a price' (needs a real price) or 'Give it away for free'."""
    if free is None:
        return ["Choose whether you sell it for a price or give it away for free."]
    if free:
        return []
    if price_cents is None:
        return ["Enter a price, or choose “Give it away for free”."]
    if not isinstance(price_cents, int) or isinstance(price_cents, bool):
        return ["Price must be a number."]
    if price_cents <= 0:
        return ["Enter a price, or choose “Give it away for free”."]
    if price_cents > MAX_PRICE_CENTS:
        return [f"Price can't be more than €{MAX_PRICE_CENTS // 100:,}."]
    return []


def _choice_with_other(value, other_text, options, label, other_label) -> list[str]:
    """A choice from the list; if it is "Other", the typed text is required too."""
    if value not in options:
        return [f"Choose a {label} from the list."]
    if value == OTHER:
        return _text(other_text, other_label, 2, MAX_OTHER_LENGTH)
    return []


def check_listing(*, title, description, free, price_cents, category, condition,
                  pickup_area, category_other=None, pickup_area_other=None,
                  available_from=None) -> list[str]:
    """Every problem with the listing's fields (empty list = all good). All fields are required."""
    errors = _text(title, "Title", 3, 80) + _text(description, "Description", 10, 2000)
    errors += check_offer(free=free, price_cents=price_cents)
    errors += _choice_with_other(category, category_other, CATEGORIES, "category",
                                 "Your category (for “Other”)")
    if condition not in CONDITIONS:
        errors.append("Choose a condition from the list.")
    errors += _choice_with_other(pickup_area, pickup_area_other, PICKUP_AREAS, "pickup area",
                                 "Your pickup area (for “Other”)")
    return errors


def _other_text(value, other_text):
    """The typed text is only kept when "Other" was chosen."""
    return other_text.strip() if value == OTHER else None


def _fields(*, title, description, free, price_cents, category, condition,
            pickup_area, category_other=None, pickup_area_other=None,
            available_from=None) -> dict:
    """The checked fields, tidied, in the shape they are stored in."""
    return {
        "title": title.strip(),
        "description": description.strip(),
        "price_cents": 0 if free else price_cents,
        "category": category,
        "category_other": _other_text(category, category_other),
        "condition": condition,
        "pickup_area": pickup_area,
        "pickup_area_other": _other_text(pickup_area, pickup_area_other),
        "available_from": available_from.isoformat() if available_from else None,
    }


def availability_text(listing: dict, today: date) -> str:
    """'Available from 10 Dec 2026' when the item is only free to collect later;
    an empty string when it's available now (no date, or a date already past)."""
    value = listing.get("available_from")
    if not value:
        return ""
    when = date.fromisoformat(value) if isinstance(value, str) else value
    if when <= today:
        return ""
    return f"Available from {when.day} {when:%b %Y}"


def listed_text(listing: dict) -> str:
    """'Listed on 20 Nov 2026' from the row's created_at; '' if it's missing.
    created_at comes back from the database as an ISO timestamp string, so we
    keep just the date part (everything before the 'T')."""
    value = listing.get("created_at")
    if not value:
        return ""
    when = date.fromisoformat(value[:10]) if isinstance(value, str) else value
    return f"Listed on {when.day} {when:%b %Y}"


def category_label(listing: dict) -> str:
    """What to show as the category: 'Furniture', or the typed text for 'Other'."""
    return (listing.get("category_other") if listing.get("category") == OTHER
            else None) or listing.get("category", "")


def pickup_label(listing: dict) -> str:
    """What to show as the pickup area: 'Carcavelos', or the typed text for 'Other'."""
    return (listing.get("pickup_area_other") if listing.get("pickup_area") == OTHER
            else None) or listing.get("pickup_area", "")


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
                   free: bool | None, price_cents: int | None, category: str | None,
                   condition: str | None, pickup_area: str | None, photos: list[bytes],
                   category_other: str | None = None,
                   pickup_area_other: str | None = None,
                   available_from: date | None = None) -> int:
    """Publish a new listing. Returns its id. Raises ListingError listing every problem."""
    seller = _seller_profile(db, seller_email)
    if seller.get("blocked_at"):  # an admin blocked this student (see admin.py)
        raise NotAllowed("Your account has been blocked, so you cannot sell.")
    fields = dict(title=title, description=description, free=free,
                  price_cents=price_cents, category=category,
                  condition=condition, pickup_area=pickup_area,
                  category_other=category_other, pickup_area_other=pickup_area_other,
                  available_from=available_from)
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
                   free: bool | None, price_cents: int | None, category: str | None,
                   condition: str | None, pickup_area: str | None,
                   keep_photo_paths: list[str] | None = None, new_photos: list[bytes] = (),
                   category_other: str | None = None,
                   pickup_area_other: str | None = None,
                   available_from: date | None = None) -> None:
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
                  condition=condition, pickup_area=pickup_area,
                  category_other=category_other, pickup_area_other=pickup_area_other,
                  available_from=available_from)
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


# --- listings with a buyer (see deals.py) -----------------------------------------
# A buyer can ask to buy a listing through the app ("Request to buy"). Once the
# seller accepted one, that deal decides the status: the seller confirms or
# cancels it on the Sales page, not with the buttons on My listings. Otherwise
# the buyer would still see "Accepted" for an item that is back on sale.
# (The names are the same as in deals.py, which can't be imported here:
# deals.py imports this file.)
_WAITING, _ACCEPTED = "requested", "accepted"
DEAL_IN_PROGRESS = ("This item is reserved for a buyer who asked through the app. "
                    "Confirm or cancel that deal on the Sales page.")


def _refuse_if_deal_in_progress(db, listing_id: int) -> list[dict]:
    """Stop if a buyer was accepted; otherwise return the requests still waiting."""
    live = db.requests_for_listing(listing_id, [_WAITING, _ACCEPTED])
    if any(request["status"] == _ACCEPTED for request in live):
        raise ListingError([DEAL_IN_PROGRESS])
    return [request for request in live if request["status"] == _WAITING]


def delete_listing(db, listing_id: int, seller_email: str) -> None:
    """Remove the listing and its photos for good.

    Not while a buyer is accepted. Requests still waiting are deleted with it.
    """
    listing, seller = _own_listing(db, listing_id, seller_email)
    _refuse_if_deal_in_progress(db, listing_id)
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
    waiting = _refuse_if_deal_in_progress(db, listing_id)
    # Only if the status is still what we just read (see deals.py, "Changing a
    # status safely"): a buyer may be accepted at this very moment.
    if not db.update_listing(listing_id, seller["id"], {"status": new_status},
                             only_if_status=listing["status"]):
        raise ListingError(["This listing just changed. Please look again."])
    # Reserved or sold outside the app: the buyers who asked get a clear "no"
    # instead of waiting for an answer that will never come.
    if new_status != ACTIVE:
        for request in waiting:
            db.update_request(request["id"], {"status": "declined"}, only_if_status=_WAITING)


def mark_reserved(db, listing_id: int, seller_email: str) -> None:
    _move(db, listing_id, seller_email, RESERVED)


def mark_sold(db, listing_id: int, seller_email: str) -> None:
    _move(db, listing_id, seller_email, SOLD)


def relist(db, listing_id: int, seller_email: str) -> None:
    _move(db, listing_id, seller_email, ACTIVE)
