"""Tests for the buyer search/sort rules in listings.py. No database needed —
these run with `pytest` on their own, which is the point of keeping the rules
out of the page and out of database.py."""

from listings import CATEGORIES, SORTS, filter_and_sort, listing_problems


def make(**changes):
    """A listing dict with sensible defaults; override any field."""
    item = {"id": 1, "seller_id": 1, "title": "", "description": "",
            "price": 0, "category": "Other", "status": "available",
            "created_at": "2026-01-01T00:00:00+00:00"}
    item.update(changes)
    return item


# --- search ------------------------------------------------------------------
def test_search_matches_title_and_description_case_insensitively():
    items = [make(title="Red Bicycle"), make(title="Desk", description="comes with a BICYCLE rack")]
    assert len(filter_and_sort(items, search="bicycle")) == 2   # one by title, one by description
    assert len(filter_and_sort(items, search="BICYCLE")) == 2   # case-insensitive
    assert filter_and_sort(items, search="spaceship") == []


# --- category ----------------------------------------------------------------
def test_category_filter():
    items = [make(title="Chair", category="Furniture"),
             make(title="Book", category="Textbooks")]
    out = filter_and_sort(items, category="Furniture")
    assert [i["title"] for i in out] == ["Chair"]
    assert len(filter_and_sort(items, category="All")) == 2


# --- price range -------------------------------------------------------------
def test_price_range_filter():
    items = [make(title="Cheap", price=5), make(title="Mid", price=50),
             make(title="Pricey", price=500)]
    out = filter_and_sort(items, min_price=10, max_price=100)
    assert [i["title"] for i in out] == ["Mid"]


# --- sold items --------------------------------------------------------------
def test_sold_items_hidden_by_default_and_shown_when_included():
    items = [make(title="A", status="available"), make(title="B", status="sold")]
    assert [i["title"] for i in filter_and_sort(items)] == ["A"]
    assert {i["title"] for i in filter_and_sort(items, include_sold=True)} == {"A", "B"}


# --- sorting -----------------------------------------------------------------
def test_sort_by_price_ascending_and_descending():
    items = [make(title="A", price=50), make(title="B", price=5), make(title="C", price=500)]
    assert [i["price"] for i in filter_and_sort(items, sort="price_asc")] == [5, 50, 500]
    assert [i["price"] for i in filter_and_sort(items, sort="price_desc")] == [500, 50, 5]


def test_sort_newest_uses_created_at():
    items = [make(title="old", created_at="2026-01-01T00:00:00+00:00"),
             make(title="new", created_at="2026-05-01T00:00:00+00:00")]
    assert [i["title"] for i in filter_and_sort(items, sort="newest")] == ["new", "old"]


# --- combined ----------------------------------------------------------------
def test_filters_combine():
    items = [make(title="Cheap textbook", category="Textbooks", price=10),
             make(title="Pricey textbook", category="Textbooks", price=300),
             make(title="Cheap chair", category="Furniture", price=10)]
    out = filter_and_sort(items, search="textbook", category="Textbooks",
                          min_price=0, max_price=50)
    assert [i["title"] for i in out] == ["Cheap textbook"]


# --- validation (used by the Sell page) --------------------------------------
def test_listing_problems_accepts_a_good_listing():
    assert listing_problems("Bike", 90, "Other") == []


def test_listing_problems_catches_bad_input():
    assert listing_problems("", 10, "Other")                      # empty title
    assert listing_problems("Bike", -5, "Other")                  # negative price
    assert "category" in " ".join(listing_problems("Bike", 10, "Nope")).lower()
    assert all(c in CATEGORIES for c in CATEGORIES)               # sanity
    assert SORTS["Newest"] == "newest"
