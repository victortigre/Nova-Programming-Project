"""Tests for area 2 (Seller: listings): accepted actions, rejected actions, edge cases.

Every test gets a fresh database in memory, so the real db.sqlite3 is never touched.
Run them with:  pytest
"""

from io import BytesIO

import pytest
from PIL import Image

import listings
from listings import ListingError, NotAllowed, NotFound

ANA = "ana@novasbe.pt"
TOM = "tom@novasbe.pt"


def photo(color=(200, 50, 50)) -> bytes:
    out = BytesIO()
    Image.new("RGB", (40, 30), color).save(out, format="JPEG")
    return out.getvalue()


GOOD = dict(title="BA II Plus calculator", description="Financial calculator, works perfectly.",
            free=False, price_cents=2000, category="Calculators & electronics",
            condition="Good", pickup_area="Nova SBE campus")


@pytest.fixture
def conn():
    connection = listings.connect(":memory:")
    yield connection
    connection.close()


def new_listing(conn, seller=ANA, photos=None, **changes) -> int:
    fields = {**GOOD, **changes}
    return listings.create_listing(conn, seller, "Ana", photos=photos or [photo()], **fields)


def edit(conn, listing_id, seller=ANA, **changes):
    listings.update_listing(conn, listing_id, seller, **{**GOOD, **changes})


# --- create listing -------------------------------------------------------------

def test_create_listing_with_all_fields(conn):
    listing = listings.get_listing(conn, new_listing(conn))
    assert listing["title"] == "BA II Plus calculator"
    assert listing["price_cents"] == 2000
    assert listing["status"] == "active"
    assert listing["seller_email"] == ANA
    assert listing["cover"] is not None


def test_text_is_trimmed(conn):
    listing = listings.get_listing(conn, new_listing(conn, title="   Desk lamp  "))
    assert listing["title"] == "Desk lamp"


def test_free_listing_is_stored_with_price_zero(conn):
    listing = listings.get_listing(conn, new_listing(conn, free=True, price_cents=1500))
    assert listing["price_cents"] == 0
    assert listings.format_price(listing["price_cents"]) == "Free"


def test_selling_needs_a_price(conn):
    with pytest.raises(ListingError, match="Enter a price"):
        new_listing(conn, free=False, price_cents=0)


@pytest.mark.parametrize("changes, message", [
    ({"title": "ab"}, "Title must be at least 3 characters."),
    ({"title": "x" * 81}, "Title must be at most 80 characters."),
    ({"description": "short"}, "Description must be at least 10 characters."),
    ({"price_cents": -100}, "Enter a price, or choose “Give it away for free”."),
    ({"price_cents": 1_000_001}, "Price can't be more than €10,000."),
    ({"price_cents": 12.5}, "Price must be a number."),
    ({"category": "Cars"}, "Choose a category from the list."),
    ({"condition": "Broken"}, "Choose a condition from the list."),
    ({"pickup_area": "Porto"}, "Choose a pickup area from the list."),
])
def test_bad_fields_are_rejected(conn, changes, message):
    with pytest.raises(ListingError) as exc:
        new_listing(conn, **changes)
    assert message in exc.value.errors


def test_every_problem_is_reported_at_once(conn):
    with pytest.raises(ListingError) as exc:
        listings.create_listing(conn, ANA, "Ana", title="", description="", free=False,
                                price_cents=0, category="?", condition="?", pickup_area="?",
                                photos=[])
    assert len(exc.value.errors) == 7


def test_only_nova_accounts_can_sell(conn):
    with pytest.raises(NotAllowed):
        new_listing(conn, seller="someone@gmail.com")


def test_seller_email_is_cleaned_up(conn):
    listing_id = new_listing(conn, seller="  ANA@NovaSBE.pt ")
    assert listings.get_listing(conn, listing_id)["seller_email"] == ANA


def test_nothing_is_saved_when_input_is_wrong(conn):
    with pytest.raises(ListingError):
        new_listing(conn, title="")
    assert listings.feed_listings(conn) == []


# --- photo upload ---------------------------------------------------------------

def test_at_least_one_photo_is_required(conn):
    with pytest.raises(ListingError) as exc:
        listings.create_listing(conn, ANA, "Ana", photos=[], **GOOD)
    assert exc.value.errors == ["Add at least one photo."]


def test_five_photos_allowed_six_rejected(conn):
    listing_id = new_listing(conn, photos=[photo()] * 5)
    assert len(listings.get_photos(conn, listing_id)) == 5
    with pytest.raises(ListingError, match="at most 5 photos"):
        new_listing(conn, photos=[photo()] * 6)


def test_non_image_file_is_rejected(conn):
    with pytest.raises(ListingError, match="couldn't be read"):
        new_listing(conn, photos=[b"\xff\xd8\xff this is not a photo"])


def test_first_photo_is_the_cover(conn):
    red, blue = photo((255, 0, 0)), photo((0, 0, 255))
    listing_id = new_listing(conn, photos=[red, blue])
    cover = Image.open(BytesIO(listings.get_listing(conn, listing_id)["cover"])).convert("RGB")
    assert cover.getpixel((5, 5))[0] > 200  # red


# --- edit listing ---------------------------------------------------------------

def test_seller_can_change_any_field(conn):
    listing_id = new_listing(conn)
    edit(conn, listing_id, title="BA II Plus - price drop", free=True, condition="Fair")
    listing = listings.get_listing(conn, listing_id)
    assert (listing["title"], listing["price_cents"], listing["condition"]) == \
        ("BA II Plus - price drop", 0, "Fair")


def test_other_people_cannot_edit(conn):
    listing_id = new_listing(conn)
    with pytest.raises(NotAllowed):
        edit(conn, listing_id, seller=TOM, title="Hacked")
    assert listings.get_listing(conn, listing_id)["title"] == GOOD["title"]


def test_editing_a_missing_listing(conn):
    with pytest.raises(NotFound):
        edit(conn, 999)


def test_edit_keeps_photos_by_default(conn):
    listing_id = new_listing(conn, photos=[photo(), photo()])
    edit(conn, listing_id, title="New title")
    assert len(listings.get_photos(conn, listing_id)) == 2


def test_edit_can_remove_reorder_and_add_photos(conn):
    listing_id = new_listing(conn, photos=[photo(), photo(), photo()])
    first, second, third = [p["id"] for p in listings.get_photos(conn, listing_id)]
    old = {p["id"]: p["data"] for p in listings.get_photos(conn, listing_id)}
    edit(conn, listing_id, keep_photo_ids=[third, first], new_photos=[photo((0, 255, 0))])
    stored = [p["data"] for p in listings.get_photos(conn, listing_id)]
    assert stored[:2] == [old[third], old[first]]  # third photo is now the cover
    assert len(stored) == 3


def test_edit_cannot_remove_every_photo(conn):
    listing_id = new_listing(conn)
    with pytest.raises(ListingError, match="at least one photo"):
        edit(conn, listing_id, keep_photo_ids=[])
    assert len(listings.get_photos(conn, listing_id)) == 1  # nothing changed


def test_edit_cannot_go_over_five_photos(conn):
    listing_id = new_listing(conn, photos=[photo()] * 4)
    with pytest.raises(ListingError, match="at most 5"):
        edit(conn, listing_id, new_photos=[photo(), photo()])


def test_edit_cannot_steal_photos_from_another_listing(conn):
    mine = new_listing(conn)
    other = new_listing(conn, seller=TOM)
    their_photo = listings.get_photos(conn, other)[0]["id"]
    with pytest.raises(NotAllowed):
        edit(conn, mine, keep_photo_ids=[their_photo])


# --- delete listing -------------------------------------------------------------

def test_seller_can_delete(conn):
    listing_id = new_listing(conn)
    listings.delete_listing(conn, listing_id, ANA)
    assert listings.get_listing(conn, listing_id) is None
    assert listings.get_photos(conn, listing_id) == []  # photos removed too
    assert listings.feed_listings(conn) == []


def test_other_people_cannot_delete(conn):
    listing_id = new_listing(conn)
    with pytest.raises(NotAllowed):
        listings.delete_listing(conn, listing_id, TOM)
    assert listings.get_listing(conn, listing_id) is not None


# --- reserved / sold / relist ---------------------------------------------------

def test_reserved_listing_stays_visible_with_its_status(conn):
    listing_id = new_listing(conn)
    listings.mark_reserved(conn, listing_id, ANA)
    feed = listings.feed_listings(conn)
    assert [(item["id"], item["status"]) for item in feed] == [(listing_id, "reserved")]


def test_sold_listing_disappears_from_the_feed(conn):
    listing_id = new_listing(conn)
    listings.mark_sold(conn, listing_id, ANA)
    assert listings.feed_listings(conn) == []


def test_reserved_item_can_be_sold(conn):
    listing_id = new_listing(conn)
    listings.mark_reserved(conn, listing_id, ANA)
    listings.mark_sold(conn, listing_id, ANA)
    assert listings.get_listing(conn, listing_id)["status"] == "sold"


def test_relist_brings_items_back(conn):
    reserved, sold = new_listing(conn), new_listing(conn)
    listings.mark_reserved(conn, reserved, ANA)
    listings.mark_sold(conn, sold, ANA)
    listings.relist(conn, reserved, ANA)
    listings.relist(conn, sold, ANA)
    assert {item["status"] for item in listings.feed_listings(conn)} == {"active"}


@pytest.mark.parametrize("setup, action, message", [
    ([], listings.relist, "already active"),
    ([listings.mark_sold], listings.mark_reserved, "Only an active listing"),
    ([listings.mark_sold], listings.mark_sold, "already sold"),
])
def test_status_changes_that_make_no_sense_are_rejected(conn, setup, action, message):
    listing_id = new_listing(conn)
    for step in setup:
        step(conn, listing_id, ANA)
    with pytest.raises(ListingError, match=message):
        action(conn, listing_id, ANA)


@pytest.mark.parametrize("action", [listings.mark_reserved, listings.mark_sold, listings.relist])
def test_only_the_seller_can_change_the_status(conn, action):
    listing_id = new_listing(conn)
    if action is listings.relist:  # relist needs a reserved/sold item to start from
        listings.mark_reserved(conn, listing_id, ANA)
    before = listings.get_listing(conn, listing_id)["status"]
    with pytest.raises(NotAllowed):
        action(conn, listing_id, TOM)
    assert listings.get_listing(conn, listing_id)["status"] == before


# --- my listings ----------------------------------------------------------------

def test_my_listings_grouped_by_status_and_only_mine(conn):
    active, reserved, sold = new_listing(conn), new_listing(conn), new_listing(conn)
    new_listing(conn, seller=TOM)
    listings.mark_reserved(conn, reserved, ANA)
    listings.mark_sold(conn, sold, ANA)
    groups = listings.my_listings(conn, ANA)
    assert [item["id"] for item in groups["active"]] == [active]
    assert [item["id"] for item in groups["reserved"]] == [reserved]
    assert [item["id"] for item in groups["sold"]] == [sold]


def test_my_listings_newest_first(conn):
    first, second = new_listing(conn), new_listing(conn)
    assert [item["id"] for item in listings.my_listings(conn, ANA)["active"]] == [second, first]


def test_my_listings_empty(conn):
    assert listings.my_listings(conn, ANA) == {"active": [], "reserved": [], "sold": []}


# --- money ----------------------------------------------------------------------

def test_money_conversion():
    assert listings.euros_to_cents(12.5) == 1250
    assert listings.euros_to_cents(0.1 + 0.2) == 30
    assert listings.format_price(1250) == "€12.50"
    assert listings.format_price(123456) == "€1,234.56"
