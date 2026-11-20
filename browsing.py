"""Browsing: what a buyer does — search the marketplace feed and save listings.

Search and sort are PURE: they work on a plain list of listing dicts (the shape
database.feed_listings returns), so the buyer's whole search behaviour is tested
without the database (tests/test_browsing.py).

The saved-listings helpers take `db` first, exactly like listings.py: the pages
pass the real `database` module, the tests pass the in-memory fake database.
"""

# Buyers filter by the same categories, conditions and pickup areas sellers pick.
from listings import CATEGORIES, CONDITIONS, PICKUP_AREAS  # noqa: F401

# The label shown in the "Sort by" box -> how to sort.
SORTS = {
    "Newest": "newest",
    "Price: low to high": "price_asc",
    "Price: high to low": "price_desc",
    "Available until: soonest": "available_soonest",
}


def search_and_sort(items: list[dict], *, query: str | None = None,
                    category: str = "All", min_cents: int | None = None,
                    max_cents: int | None = None, conditions: list[str] | None = None,
                    pickup_areas: list[str] | None = None,
                    sort: str = "newest") -> list[dict]:
    """Return the listings to show a buyer, after search + filters, in order.

    `items` is a list of listing dicts with at least: title, description,
    price_cents, category, created_at. Pure — no database, no Streamlit.

    conditions / pickup_areas: keep only listings with one of these values.
    None or an empty list means "any" (nothing ticked = no filter).
    """
    needle = (query or "").strip().lower()
    result = []
    for item in items:
        if category and category != "All" and item.get("category") != category:
            continue
        if needle:
            haystack = f"{item.get('title', '')} {item.get('description', '')}".lower()
            if needle not in haystack:
                continue
        price = item.get("price_cents", 0)
        if min_cents is not None and price < min_cents:
            continue
        if max_cents is not None and price > max_cents:
            continue
        if conditions and item.get("condition") not in conditions:
            continue
        if pickup_areas and item.get("pickup_area") not in pickup_areas:
            continue
        result.append(item)

    if sort == "price_asc":
        result.sort(key=lambda item: item.get("price_cents", 0))
    elif sort == "price_desc":
        result.sort(key=lambda item: item.get("price_cents", 0), reverse=True)
    elif sort == "available_soonest":
        # Items that stop being available soonest first; items without a date last.
        result.sort(key=lambda item: (not item.get("available_until"),
                                      str(item.get("available_until") or "")))
    else:  # "newest" — a later created_at is newer (an ISO string, or the fake's counter)
        result.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return result


# --- saved listings (a buyer's wishlist) --------------------------------------

def saved_ids(db, profile_id: int) -> set[int]:
    """The set of listing ids this buyer has saved."""
    return set(db.favorite_ids(profile_id))


def saved_listings(db, profile_id: int) -> list[dict]:
    """The buyer's saved listings in full, newest-saved first."""
    return db.favorite_listings(profile_id)


def toggle_saved(db, profile_id: int, listing_id: int) -> bool:
    """Save the listing if it isn't saved yet, otherwise unsave it.

    Returns the new state: True if it is now saved, False if it was removed.
    """
    if listing_id in db.favorite_ids(profile_id):
        db.remove_favorite(profile_id, listing_id)
        return False
    db.add_favorite(profile_id, listing_id)
    return True
