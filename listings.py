"""Listings: the rules for searching, sorting and checking marketplace listings.

Nothing here talks to the database or to the screen. It works on plain lists of
listing dictionaries (the shape database.py returns), so the buyer's search and
sort can be tested on their own (tests/test_listings.py).
"""

# The fixed set of categories a listing can have. Shared by Browse and Sell.
CATEGORIES = ["Textbooks", "Furniture", "Electronics", "Tickets", "Housing", "Other"]

# The label shown in the "Sort by" box -> the sort it means.
SORTS = {
    "Newest": "newest",
    "Price: low to high": "price_asc",
    "Price: high to low": "price_desc",
}

MAX_TITLE_LENGTH = 80


def listing_problems(title: str | None, price, category: str | None) -> list[str]:
    """What is wrong with a new listing, as messages for the person.

    An empty list means the listing may be posted. Used by the Sell page.
    """
    problems = []

    title = (title or "").strip()
    if not title:
        problems.append("Please give your listing a title.")
    elif len(title) > MAX_TITLE_LENGTH:
        problems.append(f"The title can be at most {MAX_TITLE_LENGTH} characters long.")

    if price is None or price < 0:
        problems.append("The price cannot be negative.")

    if category not in CATEGORIES:
        problems.append("Please choose a category.")

    return problems


def filter_and_sort(listings: list[dict], search: str | None = None,
                    category: str = "All", min_price: float | None = None,
                    max_price: float | None = None, include_sold: bool = False,
                    sort: str = "newest") -> list[dict]:
    """Return the listings a buyer should see, after search + filters, in order.

    Each listing is a dict with at least: title, description, price, category,
    status, created_at. Pure function — no database, no Streamlit — so the whole
    buyer search behaviour is covered by tests.
    """
    needle = (search or "").strip().lower()
    result = []
    for item in listings:
        if not include_sold and item.get("status") != "available":
            continue
        if category and category != "All" and item.get("category") != category:
            continue
        if needle:
            haystack = f"{item.get('title', '')} {item.get('description', '')}".lower()
            if needle not in haystack:
                continue
        price = item.get("price", 0)
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        result.append(item)

    if sort == "price_asc":
        result.sort(key=lambda x: x.get("price", 0))
    elif sort == "price_desc":
        result.sort(key=lambda x: x.get("price", 0), reverse=True)
    else:  # "newest" — ISO timestamps sort correctly as text
        result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result
