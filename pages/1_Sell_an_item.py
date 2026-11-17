"""Sell an item: create a new listing, or edit one from "My listings".

The page only collects the input and shows messages. The rules themselves
(and the check that you own the listing) are in listings.py.
"""

import streamlit as st

import listings
from seller_login import require_nova_student

SELL = "Sell for a price"
FREE = "Give it away for free"

st.set_page_config(page_title="Sell an item · Nova Marketplace", page_icon="➕")

me = require_nova_student()
conn = listings.connect()

# --- new listing, or editing one? --------------------------------------------
editing = None
edit_id = st.session_state.get("edit_listing_id")
if edit_id:
    editing = listings.get_listing(conn, edit_id)
    if editing is None or editing["seller_email"] != me["email"]:
        st.session_state.pop("edit_listing_id", None)
        editing = None

st.title("Edit listing" if editing else "Sell an item")
if editing and st.button("← Cancel editing"):
    st.session_state.pop("edit_listing_id", None)
    st.switch_page("pages/2_My_listings.py")


def start_value(field, fallback):
    """Pre-fill with the listing's current value when editing."""
    return editing[field] if editing else fallback


def choice_index(options, field, fallback_index=0):
    return options.index(editing[field]) if editing else fallback_index


# --- price or free -----------------------------------------------------------
# Outside the form on purpose: inside a form, the page only updates when you
# submit, so the price box couldn't appear and disappear.
offer = st.radio("How do you want to offer it?", [SELL, FREE], horizontal=True,
                 index=1 if editing and editing["price_cents"] == 0 else 0)
free = offer == FREE

# --- current photos (only when editing) --------------------------------------
keep_ids = None
if editing:
    current_photos = listings.get_photos(conn, editing["id"])
    st.subheader("Current photos")
    st.caption("Untick a photo to remove it. The first photo you keep is the cover.")
    keep_ids = []
    columns = st.columns(max(len(current_photos), 1))
    for number, (column, photo) in enumerate(zip(columns, current_photos), start=1):
        with column:
            st.image(photo["data"])
            label = "Keep (cover)" if number == 1 else "Keep"
            if st.checkbox(label, value=True, key=f"keep-{photo['id']}"):
                keep_ids.append(photo["id"])

# --- the form ----------------------------------------------------------------
with st.form("listing_form"):
    title = st.text_input("Title", value=start_value("title", ""), max_chars=80,
                          placeholder="e.g. Texas Instruments BA II Plus calculator")
    description = st.text_area("Description", value=start_value("description", ""),
                               max_chars=2000,
                               placeholder="Condition details, edition, size, why you're selling...")
    price = 0.0
    if not free:
        price = st.number_input("Price (€)", min_value=0.0,
                                max_value=listings.MAX_PRICE_CENTS / 100, step=0.5,
                                format="%.2f",
                                value=editing["price_cents"] / 100 if editing else 0.0)

    left, middle, right = st.columns(3)
    category = left.selectbox("Category", listings.CATEGORIES,
                              index=choice_index(listings.CATEGORIES, "category"))
    condition = middle.selectbox("Condition", listings.CONDITIONS,
                                 index=choice_index(listings.CONDITIONS, "condition", 1))
    pickup_area = right.selectbox("Pickup area", listings.PICKUP_AREAS,
                                  index=choice_index(listings.PICKUP_AREAS, "pickup_area"))

    uploads = st.file_uploader(
        "Add photos (JPG or PNG)" if editing else "Photos (1 to 5, JPG or PNG)",
        type=["jpg", "jpeg", "png"], accept_multiple_files=True,
    )
    submitted = st.form_submit_button("Save changes" if editing else "Publish listing",
                                      type="primary")

# --- saving --------------------------------------------------------------------
if submitted:
    fields = dict(title=title, description=description, free=free,
                  price_cents=listings.euros_to_cents(price), category=category,
                  condition=condition, pickup_area=pickup_area)
    new_photos = [upload.getvalue() for upload in uploads or []]
    try:
        if editing:
            listings.update_listing(conn, editing["id"], me["email"], keep_photo_ids=keep_ids,
                                    new_photos=new_photos, **fields)
        else:
            listings.create_listing(conn, me["email"], me["name"], photos=new_photos, **fields)
    except listings.ListingError as exc:
        for message in exc.errors:  # show every problem at once
            st.error(message)
    except (listings.NotAllowed, listings.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state.pop("edit_listing_id", None)
        st.success("Changes saved!" if editing else "Your listing is live! 🎉")
        st.page_link("pages/2_My_listings.py", label="Go to My listings", icon="📦")
