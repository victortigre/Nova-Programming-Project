"""Sell an item: create a new listing, or edit one from "My listings".

Every question is required, for items for sale and for free items alike.
Choosing "Other" as category or pickup area opens a box to type what it is.

The page only collects the input and shows messages. The rules themselves
(and the check that you own the listing) are in listings.py.
"""

from datetime import date

import streamlit as st

import database
import listings
import payments
from accounts import logged_in_user, verified_nova_email

SELL = "Sell for a price"
FREE = "Give it away for free"
PICK = "Choose..."

# Who is using this page? The email always comes from the login, never from a form.
email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

# Every listing belongs to a profile, so buyers can see who is selling.
profile = database.get_profile(email)
if profile is None:
    st.header("Sell an item")
    st.info("Fill in your profile first, so buyers know who they are dealing with.")
    st.page_link("views/profile.py", label="Fill in my profile")
    st.stop()

# --- new listing, or editing one? --------------------------------------------
editing = None
edit_id = st.session_state.get("edit_listing_id")
if edit_id:
    editing = listings.get_listing(database, edit_id)
    if editing is None or editing["seller_id"] != profile["id"]:
        st.session_state.pop("edit_listing_id", None)
        editing = None

st.header("Edit listing" if editing else "Sell an item")
if not payments.has_bank_details(profile):
    st.warning("Add your bank details on My profile before selling something: buyers "
               "pay you by bank transfer. You can still give items away for free.",
               icon=":material/account_balance:")
    st.page_link("views/profile.py", label="Add my bank details",
                 icon=":material/account_balance:")
if editing and st.button("← Cancel editing"):
    st.session_state.pop("edit_listing_id", None)
    st.switch_page("views/my_listings.py")

# Every field gets a key that changes after publishing, so the page starts
# empty again for the next item.
form_round = st.session_state.get("sell_form_round", 0)
prefix = f"edit-{editing['id']}" if editing else f"new-{form_round}"


def key(name: str) -> str:
    return f"{prefix}-{name}"


def start_value(field, fallback):
    """Pre-fill with the listing's current value when editing."""
    return editing.get(field) or fallback if editing else fallback


def start_index(options, field):
    """When editing, the listing's current choice; for a new listing, nothing chosen."""
    if editing and editing.get(field) in options:
        return options.index(editing[field])
    return None


st.page_link("views/house_rules.py", label="Before you post, read the house rules")
st.caption("All fields are required.")

# --- price or free -----------------------------------------------------------
offer_index = None
if editing:
    offer_index = 1 if editing["price_cents"] == 0 else 0
offer = st.radio("How do you want to offer it?", [SELL, FREE], horizontal=True,
                 index=offer_index, key=key("offer"))
free = None if offer is None else offer == FREE

# --- the questions -----------------------------------------------------------
title = st.text_input("Title", value=start_value("title", ""), max_chars=80, key=key("title"),
                      placeholder="e.g. Texas Instruments BA II Plus calculator")
description = st.text_area("Description", value=start_value("description", ""),
                           max_chars=2000, key=key("description"),
                           placeholder="Condition details, edition, size, why you're selling...")

price_text = ""
if offer == SELL:
    # A text box (so "15,50" with a comma works too) with - and + buttons.
    price_key = key("price")
    if price_key not in st.session_state:
        st.session_state[price_key] = (listings.price_text(editing["price_cents"])
                                       if editing and editing["price_cents"] else "")

    def change_price(step_cents: int) -> None:
        try:
            cents = listings.parse_price(st.session_state[price_key]) or 0
        except ValueError:
            cents = 0
        st.session_state[price_key] = listings.price_text(min(max(0, cents + step_cents), listings.MAX_PRICE_CENTS))

    box, minus, plus = st.columns([8, 1, 1], vertical_alignment="bottom")
    price_text = box.text_input(f"Price (€, max {listings.MAX_PRICE_CENTS // 100:,})", key=price_key,
                                placeholder="e.g. 15,50")
    minus.button("−", key=key("price-minus"), on_click=change_price, args=(-50,),
                 width="stretch", help="€0.50 less")
    plus.button("+", key=key("price-plus"), on_click=change_price, args=(50,),
                width="stretch", help="€0.50 more")

left, middle, right = st.columns(3)
with left:
    category = st.selectbox("Category", listings.CATEGORIES, key=key("category"),
                            index=start_index(listings.CATEGORIES, "category"),
                            placeholder=PICK)
    category_other = None
    if category == listings.OTHER:
        category_other = st.text_input("Which category?", key=key("category-other"),
                                       max_chars=listings.MAX_OTHER_LENGTH,
                                       value=start_value("category_other", ""),
                                       placeholder="e.g. Bike accessories")
with middle:
    condition = st.selectbox("Condition", listings.CONDITIONS, key=key("condition"),
                             index=start_index(listings.CONDITIONS, "condition"),
                             placeholder=PICK)
with right:
    pickup_area = st.selectbox("Pickup area", listings.PICKUP_AREAS, key=key("pickup"),
                               index=start_index(listings.PICKUP_AREAS, "pickup_area"),
                               placeholder=PICK)
    pickup_area_other = None
    if pickup_area == listings.OTHER:
        pickup_area_other = st.text_input("Which pickup area?", key=key("pickup-other"),
                                          max_chars=listings.MAX_OTHER_LENGTH,
                                          value=start_value("pickup_area_other", ""),
                                          placeholder="e.g. Saldanha metro station")

# --- when it's available (optional) -------------------------------------------
saved_available = None
if editing and editing.get("available_from"):
    saved_available = date.fromisoformat(editing["available_from"])
available_from = None
if st.checkbox("I can only hand it over from a later date",
               value=saved_available is not None, key=key("available-later")):
    available_from = st.date_input("Available from", value=saved_available or date.today(),
                                   min_value=date.today(), format="DD/MM/YYYY",
                                   key=key("available-from"))

# --- current photos (only when editing) --------------------------------------
keep_paths = None
if editing:
    current_photos = listings.get_photos(database, editing["id"])
    st.subheader("Current photos")
    st.caption("Untick a photo to remove it. The first photo you keep is the cover.")
    keep_paths = []
    columns = st.columns(max(len(current_photos), 1))
    for number, (column, path) in enumerate(zip(columns, current_photos), start=1):
        with column:
            st.image(database.listing_photo_url(path))
            label = "Keep (cover)" if number == 1 else "Keep"
            if st.checkbox(label, value=True, key=f"keep-{path}"):
                keep_paths.append(path)

uploads = st.file_uploader(
    "Add photos (JPG or PNG)" if editing else "Photos (1 to 5, JPG or PNG)",
    type=["jpg", "jpeg", "png"], accept_multiple_files=True, key=key("photos"),
)

# --- saving --------------------------------------------------------------------
if st.button("Save changes" if editing else "Publish listing", type="primary"):
    price_problem = None
    try:
        price_cents = listings.parse_price(price_text)
    except ValueError as exc:
        price_cents, price_problem = None, str(exc)
    fields = dict(
        title=title, description=description, free=free, price_cents=price_cents,
        category=category, category_other=category_other, condition=condition,
        pickup_area=pickup_area, pickup_area_other=pickup_area_other,
        available_from=available_from,
    )
    new_photos = [upload.getvalue() for upload in uploads or []]
    try:
        if editing:
            listings.update_listing(database, editing["id"], email, keep_photo_paths=keep_paths,
                                    new_photos=new_photos, **fields)
        else:
            listings.create_listing(database, email, photos=new_photos, **fields)
    except listings.ListingError as exc:
        messages = exc.errors
        if price_problem:  # say what was wrong with the typed price
            messages = [price_problem if m.startswith("Enter a price") else m for m in messages]
        for message in messages:  # show every problem at once
            st.error(message)
    except (listings.NotAllowed, listings.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state.pop("edit_listing_id", None)
        st.session_state["sell_form_round"] = form_round + 1  # empty page for the next item
        # Show the message on "My listings", where the new or edited listing now is.
        st.session_state["listing_message"] = ("Changes saved!" if editing
                                               else "Your listing is live! 🎉")
        st.switch_page("views/my_listings.py")
