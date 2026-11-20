"""Tests for area 2 (Seller: listings): accepted actions, rejected actions, edge cases.

Every test gets a fresh pretend database in memory (tests/fake_database.py),
so the real Supabase database is never touched.
Run them with:  pytest
"""

from io import BytesIO

import pytest
from PIL import Image

import deals
import listings
from fake_database import FakeDatabase
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
def db():
    """A pretend database in which Ana and Tom already have a profile."""
    db = FakeDatabase()
    for email in (ANA, TOM):
        profile = db.add_profile(email)
        # Nova credits, so they can ask to buy priced items (see wallet.py).
        db.wallet_add_entry({"profile_id": profile["id"], "amount_cents": 100_000,
                             "kind": "top_up", "request_id": None, "note": None})
    return db


def new_listing(db, seller=ANA, photos=None, **changes) -> int:
    fields = {**GOOD, **changes}
    return listings.create_listing(db, seller, photos=photos or [photo()], **fields)


def edit(db, listing_id, seller=ANA, **changes):
    listings.update_listing(db, listing_id, seller, **{**GOOD, **changes})


# --- create listing -------------------------------------------------------------

def test_create_listing_with_all_fields(db):
    listing = listings.get_listing(db, new_listing(db))
    assert listing["title"] == "BA II Plus calculator"
    assert listing["price_cents"] == 2000
    assert listing["status"] == "active"
    assert listing["seller_id"] == db.get_profile(ANA)["id"]
    assert len(listing["photo_paths"]) == 1


def test_text_is_trimmed(db):
    listing = listings.get_listing(db, new_listing(db, title="   Desk lamp  "))
    assert listing["title"] == "Desk lamp"


def test_free_listing_is_stored_with_price_zero(db):
    listing = listings.get_listing(db, new_listing(db, free=True, price_cents=1500))
    assert listing["price_cents"] == 0
    assert listings.format_price(listing["price_cents"]) == "Free"


def test_selling_needs_a_price(db):
    with pytest.raises(ListingError, match="Enter a price"):
        new_listing(db, free=False, price_cents=0)


@pytest.mark.parametrize("changes, message", [
    ({"title": "ab"}, "Title must be at least 3 characters."),
    ({"title": "x" * 81}, "Title must be at most 80 characters."),
    ({"description": "short"}, "Description must be at least 10 characters."),
    ({"price_cents": -100}, "Enter a price, or choose “Give it away for free”."),
    ({"price_cents": 500_001}, "Price can't be more than €5,000."),
    ({"price_cents": 12.5}, "Price must be a number."),
    ({"category": "Cars"}, "Choose a category from the list."),
    ({"condition": "Broken"}, "Choose a condition from the list."),
    ({"pickup_area": "Porto"}, "Choose a pickup area from the list."),
])
def test_bad_fields_are_rejected(db, changes, message):
    with pytest.raises(ListingError) as exc:
        new_listing(db, **changes)
    assert message in exc.value.errors


def test_every_problem_is_reported_at_once(db):
    with pytest.raises(ListingError) as exc:
        listings.create_listing(db, ANA, title="", description="", free=False,
                                price_cents=0, category="?", condition="?", pickup_area="?",
                                photos=[])
    assert len(exc.value.errors) == 7


# --- every question is required -------------------------------------------------

def test_nothing_chosen_is_rejected_with_one_message_per_question(db):
    with pytest.raises(ListingError) as exc:
        listings.create_listing(db, ANA, title="", description="", free=None,
                                price_cents=None, category=None, condition=None,
                                pickup_area=None, photos=[])
    assert exc.value.errors == [
        "Title must be at least 3 characters.",
        "Description must be at least 10 characters.",
        "Choose whether you sell it for a price or give it away for free.",
        "Choose a category from the list.",
        "Choose a condition from the list.",
        "Choose a pickup area from the list.",
        "Add at least one photo.",
    ]


def test_free_items_need_every_question_too(db):
    with pytest.raises(ListingError) as exc:
        new_listing(db, free=True, price_cents=None, condition=None, pickup_area=None)
    assert exc.value.errors == ["Choose a condition from the list.",
                                "Choose a pickup area from the list."]


def test_selling_without_typing_a_price(db):
    with pytest.raises(ListingError, match="Enter a price"):
        new_listing(db, free=False, price_cents=None)


@pytest.mark.parametrize("condition", ["Brand New", "Like New", "Good", "Fair"])
def test_the_four_conditions_are_accepted(db, condition):
    assert listings.get_listing(db, new_listing(db, condition=condition))["condition"] == condition


def test_old_condition_names_are_no_longer_accepted(db):
    with pytest.raises(ListingError, match="condition"):
        new_listing(db, condition="New")


# --- "Other" needs a typed answer -----------------------------------------------

@pytest.mark.parametrize("typed", [None, "", "   ", "x"])
def test_other_category_needs_a_typed_category(db, typed):
    with pytest.raises(ListingError, match="Your category"):
        new_listing(db, category="Other", category_other=typed)


@pytest.mark.parametrize("typed", [None, "", "   ", "x"])
def test_other_pickup_area_needs_a_typed_place(db, typed):
    with pytest.raises(ListingError, match="Your pickup area"):
        new_listing(db, pickup_area="Other", pickup_area_other=typed)


def test_typed_answers_are_too_long(db):
    with pytest.raises(ListingError) as exc:
        new_listing(db, category="Other", category_other="x" * 41,
                    pickup_area="Other", pickup_area_other="y" * 41)
    assert len(exc.value.errors) == 2


def test_other_answers_are_stored_and_shown(db):
    listing_id = new_listing(db, category="Other", category_other="  Bike accessories ",
                             pickup_area="Other", pickup_area_other="Saldanha metro")
    listing = listings.get_listing(db, listing_id)
    assert (listing["category"], listing["category_other"]) == ("Other", "Bike accessories")
    assert listings.category_label(listing) == "Bike accessories"
    assert listings.pickup_label(listing) == "Saldanha metro"


def test_typed_text_is_ignored_when_other_is_not_chosen(db):
    listing = listings.get_listing(db, new_listing(db, category_other="leftover text",
                                                   pickup_area_other="leftover text"))
    assert listing["category_other"] is None and listing["pickup_area_other"] is None
    assert listings.category_label(listing) == "Calculators & electronics"
    assert listings.pickup_label(listing) == "Nova SBE campus"


def test_editing_away_from_other_clears_the_typed_text(db):
    listing_id = new_listing(db, category="Other", category_other="Bike accessories")
    edit(db, listing_id, category="Sports")
    assert listings.get_listing(db, listing_id)["category_other"] is None


def test_editing_to_other_needs_the_typed_text(db):
    listing_id = new_listing(db)
    with pytest.raises(ListingError, match="Your pickup area"):
        edit(db, listing_id, pickup_area="Other")


def test_only_nova_accounts_can_sell(db):
    with pytest.raises(NotAllowed):
        new_listing(db, seller="someone@gmail.com")


def test_seller_email_is_cleaned_up(db):
    listing_id = new_listing(db, seller="  ANA@NovaSBE.pt ")
    assert listings.get_listing(db, listing_id)["seller_id"] == db.get_profile(ANA)["id"]


def test_sellers_need_a_profile(db):
    with pytest.raises(NotAllowed, match="Fill in your profile"):
        new_listing(db, seller="new.student@novasbe.pt")


def test_nothing_is_saved_when_input_is_wrong(db):
    with pytest.raises(ListingError):
        new_listing(db, title="")
    assert listings.feed_listings(db) == []


# --- photo upload ---------------------------------------------------------------

def test_at_least_one_photo_is_required(db):
    with pytest.raises(ListingError) as exc:
        listings.create_listing(db, ANA, photos=[], **GOOD)
    assert exc.value.errors == ["Add at least one photo."]


def test_five_photos_allowed_six_rejected(db):
    listing_id = new_listing(db, photos=[photo()] * 5)
    assert len(listings.get_photos(db, listing_id)) == 5
    with pytest.raises(ListingError, match="at most 5 photos"):
        new_listing(db, photos=[photo()] * 6)


def test_non_image_file_is_rejected(db):
    with pytest.raises(ListingError, match="couldn't be read"):
        new_listing(db, photos=[b"\xff\xd8\xff this is not a photo"])


def test_first_photo_is_the_cover(db):
    red, blue = photo((255, 0, 0)), photo((0, 0, 255))
    listing_id = new_listing(db, photos=[red, blue])
    cover_path = listings.get_photos(db, listing_id)[0]
    cover = Image.open(BytesIO(db.photos[cover_path])).convert("RGB")
    assert cover.getpixel((5, 5))[0] > 200  # red


# --- edit listing ---------------------------------------------------------------

def test_seller_can_change_any_field(db):
    listing_id = new_listing(db)
    edit(db, listing_id, title="BA II Plus - price drop", free=True, condition="Fair")
    listing = listings.get_listing(db, listing_id)
    assert (listing["title"], listing["price_cents"], listing["condition"]) == \
        ("BA II Plus - price drop", 0, "Fair")


def test_other_people_cannot_edit(db):
    listing_id = new_listing(db)
    with pytest.raises(NotAllowed):
        edit(db, listing_id, seller=TOM, title="Hacked")
    assert listings.get_listing(db, listing_id)["title"] == GOOD["title"]


def test_editing_a_missing_listing(db):
    with pytest.raises(NotFound):
        edit(db, 999)


def test_edit_keeps_photos_by_default(db):
    listing_id = new_listing(db, photos=[photo(), photo()])
    edit(db, listing_id, title="New title")
    assert len(listings.get_photos(db, listing_id)) == 2


def test_edit_can_remove_reorder_and_add_photos(db):
    listing_id = new_listing(db, photos=[photo(), photo(), photo()])
    first, second, third = listings.get_photos(db, listing_id)
    edit(db, listing_id, keep_photo_paths=[third, first], new_photos=[photo((0, 255, 0))])
    stored = listings.get_photos(db, listing_id)
    assert stored[:2] == [third, first]  # third photo is now the cover
    assert len(stored) == 3
    assert second not in db.photos  # the removed photo is deleted from storage


def test_edit_cannot_remove_every_photo(db):
    listing_id = new_listing(db)
    with pytest.raises(ListingError, match="at least one photo"):
        edit(db, listing_id, keep_photo_paths=[])
    assert len(listings.get_photos(db, listing_id)) == 1  # nothing changed


def test_edit_cannot_go_over_five_photos(db):
    listing_id = new_listing(db, photos=[photo()] * 4)
    with pytest.raises(ListingError, match="at most 5"):
        edit(db, listing_id, new_photos=[photo(), photo()])


def test_edit_cannot_steal_photos_from_another_listing(db):
    mine = new_listing(db)
    other = new_listing(db, seller=TOM)
    their_photo = listings.get_photos(db, other)[0]
    with pytest.raises(NotAllowed):
        edit(db, mine, keep_photo_paths=[their_photo])


# --- delete listing -------------------------------------------------------------

def test_seller_can_delete(db):
    listing_id = new_listing(db)
    listings.delete_listing(db, listing_id, ANA)
    assert listings.get_listing(db, listing_id) is None
    assert listings.get_photos(db, listing_id) == []
    assert db.photos == {}  # the photo files are removed too
    assert listings.feed_listings(db) == []


def test_other_people_cannot_delete(db):
    listing_id = new_listing(db)
    with pytest.raises(NotAllowed):
        listings.delete_listing(db, listing_id, TOM)
    assert listings.get_listing(db, listing_id) is not None


# --- reserved / sold / relist ---------------------------------------------------

def test_reserved_listing_stays_visible_with_its_status(db):
    listing_id = new_listing(db)
    listings.mark_reserved(db, listing_id, ANA)
    feed = listings.feed_listings(db)
    assert [(item["id"], item["status"]) for item in feed] == [(listing_id, "reserved")]


def test_sold_listing_disappears_from_the_feed(db):
    listing_id = new_listing(db)
    listings.mark_sold(db, listing_id, ANA)
    assert listings.feed_listings(db) == []


def test_reserved_item_can_be_sold(db):
    listing_id = new_listing(db)
    listings.mark_reserved(db, listing_id, ANA)
    listings.mark_sold(db, listing_id, ANA)
    assert listings.get_listing(db, listing_id)["status"] == "sold"


def test_relist_brings_items_back(db):
    reserved, sold = new_listing(db), new_listing(db)
    listings.mark_reserved(db, reserved, ANA)
    listings.mark_sold(db, sold, ANA)
    listings.relist(db, reserved, ANA)
    listings.relist(db, sold, ANA)
    assert {item["status"] for item in listings.feed_listings(db)} == {"active"}


@pytest.mark.parametrize("setup, action, message", [
    ([], listings.relist, "already active"),
    ([listings.mark_sold], listings.mark_reserved, "Only an active listing"),
    ([listings.mark_sold], listings.mark_sold, "already sold"),
])
def test_status_changes_that_make_no_sense_are_rejected(db, setup, action, message):
    listing_id = new_listing(db)
    for step in setup:
        step(db, listing_id, ANA)
    with pytest.raises(ListingError, match=message):
        action(db, listing_id, ANA)


@pytest.mark.parametrize("action", [listings.mark_reserved, listings.mark_sold, listings.relist])
def test_only_the_seller_can_change_the_status(db, action):
    listing_id = new_listing(db)
    if action is listings.relist:  # relist needs a reserved/sold item to start from
        listings.mark_reserved(db, listing_id, ANA)
    before = listings.get_listing(db, listing_id)["status"]
    with pytest.raises(NotAllowed):
        action(db, listing_id, TOM)
    assert listings.get_listing(db, listing_id)["status"] == before


# --- my listings ----------------------------------------------------------------

def test_my_listings_grouped_by_status_and_only_mine(db):
    active, reserved, sold = new_listing(db), new_listing(db), new_listing(db)
    new_listing(db, seller=TOM)
    listings.mark_reserved(db, reserved, ANA)
    listings.mark_sold(db, sold, ANA)
    groups = listings.my_listings(db, ANA)
    assert [item["id"] for item in groups["active"]] == [active]
    assert [item["id"] for item in groups["reserved"]] == [reserved]
    assert [item["id"] for item in groups["sold"]] == [sold]


def test_my_listings_newest_first(db):
    first, second = new_listing(db), new_listing(db)
    assert [item["id"] for item in listings.my_listings(db, ANA)["active"]] == [second, first]


def test_my_listings_empty(db):
    assert listings.my_listings(db, ANA) == {"active": [], "reserved": [], "sold": []}


# --- money ----------------------------------------------------------------------

@pytest.mark.parametrize("typed, cents", [
    ("15", 1500), ("15,50", 1550), ("15.5", 1550), ("€15", 1500), ("15 €", 1500),
    (" 0,99 ", 99), ("", None), (None, None),
])
def test_typed_prices_are_understood(typed, cents):
    assert listings.parse_price(typed) == cents


@pytest.mark.parametrize("typed", ["abc", "1,2,3", "-5", "15€50x"])
def test_typed_nonsense_is_not_a_price(typed):
    with pytest.raises(ValueError, match="Price must be a number"):
        listings.parse_price(typed)


def test_price_goes_back_into_the_box():
    assert listings.price_text(1550) == "15.50"
    assert listings.price_text(None) == ""


def test_price_limit_is_5000_euros(db):
    listing_id = new_listing(db, price_cents=500_000)  # exactly €5,000 is allowed
    assert listings.get_listing(db, listing_id)["price_cents"] == 500_000
    with pytest.raises(ListingError, match="more than €5,000"):
        new_listing(db, price_cents=500_001)  # €5,000.01 is not
    with pytest.raises(ListingError, match="more than €5,000"):
        edit(db, listing_id, price_cents=750_000)  # also when editing


def test_typed_price_above_5000_is_refused():
    assert listings.check_offer(free=False, price_cents=listings.parse_price("5000")) == []
    assert listings.check_offer(free=False, price_cents=listings.parse_price("5000,01")) == \
        ["Price can't be more than €5,000."]


def test_money_conversion():
    assert listings.euros_to_cents(12.5) == 1250
    assert listings.euros_to_cents(0.1 + 0.2) == 30
    assert listings.format_price(1250) == "€12.50"
    assert listings.format_price(123456) == "€1,234.56"


# --- showing titles as plain text -----------------------------------------------

def test_plain_text_escapes_a_link():
    assert listings.plain_text("[click](http://x)") == r"\[click\]\(http\://x\)"


def test_plain_text_escapes_bold():
    assert listings.plain_text("**bold**") == r"\*\*bold\*\*"


def test_plain_text_leaves_normal_text_alone():
    assert listings.plain_text("Desk lamp 2024") == "Desk lamp 2024"


# --- listings with a buyer (deals.py) -----------------------------------------
def _with_request(db, accepted: bool):
    lid = new_listing(db)
    request = deals.request_to_buy(db, lid, TOM)
    if accepted:
        deals.accept_request(db, request["id"], ANA)
    return lid, request["id"]


@pytest.mark.parametrize("action", [listings.mark_sold, listings.relist,
                                    listings.delete_listing])
def test_a_deal_in_progress_blocks_the_manual_buttons(db, action):
    lid, rid = _with_request(db, accepted=True)
    with pytest.raises(listings.ListingError, match="Sales page"):
        action(db, lid, ANA)
    assert db.get_listing(lid)["status"] == listings.RESERVED
    assert db.get_request(rid)["status"] == "accepted"


@pytest.mark.parametrize("action", [listings.mark_reserved, listings.mark_sold])
def test_reserving_or_selling_outside_the_app_declines_waiting_buyers(db, action):
    lid, rid = _with_request(db, accepted=False)
    action(db, lid, ANA)
    assert db.get_request(rid)["status"] == "declined"


def test_deleting_with_only_waiting_requests_is_allowed(db):
    lid, rid = _with_request(db, accepted=False)
    listings.delete_listing(db, lid, ANA)
    assert db.get_listing(lid) is None
    assert db.get_request(rid) is None  # deleted with the listing
