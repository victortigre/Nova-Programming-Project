"""Tests for area 3 (Buyer: browse): search, sort, and saved listings.

The search/sort tests are pure. The saved-listings tests use the in-memory fake
database (tests/fake_database.py), so the real Supabase is never touched.
Run them with:  pytest
"""

import pytest

import browsing
from fake_database import FakeDatabase

ANA = "ana@novasbe.pt"


def L(**changes):
    """A listing dict with sensible defaults; override any field."""
    item = {"id": 1, "seller_id": 1, "title": "", "description": "",
            "price_cents": 0, "category": "Other", "status": "active", "created_at": 1}
    item.update(changes)
    return item


# --- search_and_sort (pure) --------------------------------------------------
def test_search_matches_title_and_description_case_insensitively():
    items = [L(title="BA II Plus calculator"),
             L(title="Desk", description="comes with a CALCULATOR holder")]
    assert len(browsing.search_and_sort(items, query="calculator")) == 2  # title + description
    assert len(browsing.search_and_sort(items, query="CALC")) == 2        # case-insensitive
    assert browsing.search_and_sort(items, query="spaceship") == []


def test_category_filter():
    items = [L(title="Chair", category="Furniture"), L(title="Book", category="Textbooks")]
    assert [i["title"] for i in browsing.search_and_sort(items, category="Furniture")] == ["Chair"]
    assert len(browsing.search_and_sort(items, category="All")) == 2


def test_price_range_is_in_cents():
    items = [L(title="Cheap", price_cents=500), L(title="Mid", price_cents=5000),
             L(title="Pricey", price_cents=50000)]
    out = browsing.search_and_sort(items, min_cents=1000, max_cents=10000)
    assert [i["title"] for i in out] == ["Mid"]


def test_sort_by_price_ascending_and_descending():
    items = [L(title="A", price_cents=5000), L(title="B", price_cents=500), L(title="C", price_cents=50000)]
    assert [i["price_cents"] for i in browsing.search_and_sort(items, sort="price_asc")] == [500, 5000, 50000]
    assert [i["price_cents"] for i in browsing.search_and_sort(items, sort="price_desc")] == [50000, 5000, 500]


def test_sort_newest_uses_created_at():
    items = [L(title="old", created_at=1), L(title="new", created_at=9)]
    assert [i["title"] for i in browsing.search_and_sort(items, sort="newest")] == ["new", "old"]


def test_free_items_are_included_and_sort_first_by_price():
    items = [L(title="Paid", price_cents=1000), L(title="Freebie", price_cents=0)]
    assert browsing.search_and_sort(items, sort="price_asc")[0]["title"] == "Freebie"


def test_location_filter_keeps_only_the_chosen_places():
    items = [L(id=1, pickup_area="Carcavelos"), L(id=2, pickup_area="Cascais"),
             L(id=3, pickup_area="Nova SBE campus")]
    out = browsing.search_and_sort(items, pickup_areas=["Carcavelos", "Nova SBE campus"])
    assert sorted(i["id"] for i in out) == [1, 3]


def test_condition_filter_keeps_only_the_chosen_conditions():
    items = [L(id=1, condition="Brand New"), L(id=2, condition="Fair"),
             L(id=3, condition="Like New")]
    out = browsing.search_and_sort(items, conditions=["Brand New", "Like New"])
    assert sorted(i["id"] for i in out) == [1, 3]


@pytest.mark.parametrize("nothing_chosen", [None, []])
def test_choosing_no_location_or_condition_shows_everything(nothing_chosen):
    items = [L(id=1, condition="Good", pickup_area="Oeiras"), L(id=2, condition="Fair")]
    out = browsing.search_and_sort(items, conditions=nothing_chosen,
                                   pickup_areas=nothing_chosen)
    assert len(out) == 2


def test_location_and_condition_combine_with_the_other_filters():
    items = [
        L(id=1, category="Furniture", price_cents=2000, condition="Good", pickup_area="Carcavelos"),
        L(id=2, category="Furniture", price_cents=2000, condition="Fair", pickup_area="Carcavelos"),
        L(id=3, category="Furniture", price_cents=2000, condition="Good", pickup_area="Cascais"),
        L(id=4, category="Textbooks", price_cents=2000, condition="Good", pickup_area="Carcavelos"),
        L(id=5, category="Furniture", price_cents=90000, condition="Good", pickup_area="Carcavelos"),
    ]
    out = browsing.search_and_sort(items, category="Furniture", max_cents=100_000 // 2,
                                   conditions=["Good"], pickup_areas=["Carcavelos"])
    assert [i["id"] for i in out] == [1]


def test_buyers_choose_from_the_same_lists_as_sellers():
    import listings
    assert browsing.CONDITIONS == listings.CONDITIONS
    assert browsing.PICKUP_AREAS == listings.PICKUP_AREAS


def test_filters_combine():
    items = [L(title="Cheap textbook", category="Textbooks", price_cents=1000),
             L(title="Pricey textbook", category="Textbooks", price_cents=30000),
             L(title="Cheap chair", category="Furniture", price_cents=1000)]
    out = browsing.search_and_sort(items, query="textbook", category="Textbooks", max_cents=5000)
    assert [i["title"] for i in out] == ["Cheap textbook"]


# --- saved listings (via the fake database) ----------------------------------
@pytest.fixture
def db():
    db = FakeDatabase()
    db.add_profile(ANA)
    return db


def a_listing(db, seller_id=2):
    return db.insert_listing({"seller_id": seller_id, "title": "Lamp", "description": "x",
                              "price_cents": 500, "category": "Other", "condition": "Good",
                              "pickup_area": "Other", "photo_paths": []})


def test_toggle_saves_then_unsaves(db):
    buyer = db.get_profile(ANA)["id"]
    lid = a_listing(db)["id"]
    assert browsing.toggle_saved(db, buyer, lid) is True
    assert browsing.saved_ids(db, buyer) == {lid}
    assert [x["id"] for x in browsing.saved_listings(db, buyer)] == [lid]
    assert browsing.toggle_saved(db, buyer, lid) is False
    assert browsing.saved_ids(db, buyer) == set()
    assert browsing.saved_listings(db, buyer) == []


def test_saving_twice_keeps_a_single_entry(db):
    buyer = db.get_profile(ANA)["id"]
    lid = a_listing(db)["id"]
    db.add_favorite(buyer, lid)
    db.add_favorite(buyer, lid)
    assert browsing.saved_ids(db, buyer) == {lid}
    assert len(browsing.saved_listings(db, buyer)) == 1


def test_saved_listings_are_newest_saved_first(db):
    buyer = db.get_profile(ANA)["id"]
    first = a_listing(db)["id"]
    second = a_listing(db)["id"]
    db.add_favorite(buyer, first)
    db.add_favorite(buyer, second)
    assert [x["id"] for x in browsing.saved_listings(db, buyer)] == [second, first]
