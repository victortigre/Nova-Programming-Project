"""Browse: search the marketplace, save listings and reach a seller — BUYER side.

Reads listings and favourites through database.py; all the searching and sorting
rules live in listings.py. app.py already lets only verified Nova students in, and
we check again here, because the rule is to check where the action happens.
"""

import streamlit as st

import database
from accounts import verified_nova_email
from listings import CATEGORIES, SORTS, filter_and_sort

email = verified_nova_email(st.user.to_dict())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("Browse")

me = database.get_profile(email)
my_id = me["id"] if me else None

# The listings/favorites tables must exist. If the database has not been set up
# with them yet, show a clear message instead of a raw error.
try:
    database.list_listings(include_sold=True)
except Exception:
    st.info(
        "The marketplace listings are not set up in the database yet. "
        "Whoever manages the database needs to run `database_setup.sql` "
        "(it adds the listings and favorites tables)."
    )
    st.stop()

saved_ids = database.favorite_listing_ids(my_id) if my_id else set()


# --- actions (run on a click, before the page redraws) ------------------------
def open_listing(listing_id):
    st.session_state["selected_listing"] = listing_id


def back_to_list():
    st.session_state.pop("selected_listing", None)


def toggle_favorite(listing_id):
    if listing_id in database.favorite_listing_ids(my_id):
        database.remove_favorite(my_id, listing_id)
    else:
        database.add_favorite(my_id, listing_id)


def price_text(item):
    return f"€{float(item['price']):.0f}"


# --- detail view --------------------------------------------------------------
selected = st.session_state.get("selected_listing")
if selected is not None:
    item = database.get_listing(selected)
    if item is None:
        back_to_list()
        st.rerun()
    st.button("← Back to results", on_click=back_to_list)
    status = "✅ available" if item["status"] == "available" else "🔴 sold"
    st.subheader(item["title"])
    st.markdown(f"**{price_text(item)}** · {item['category']} · {status}")
    st.caption(f"Sold by {item['seller_name']}")
    st.write(item["description"] or "_No description._")

    if my_id and my_id != item["seller_id"]:
        is_saved = selected in saved_ids
        st.button("💔 Remove from saved" if is_saved else "🤍 Save",
                  on_click=toggle_favorite, args=(selected,))
        # Reaching the seller goes through their public profile page (part 1/5).
        st.page_link("views/public_profile.py",
                     label=f"View {item['seller_name']}'s profile to get in touch",
                     query_params={"id": item["seller_id"]})
    elif my_id == item["seller_id"]:
        st.caption("This is your own listing.")
    elif not my_id:
        st.info("Fill in your profile first to save listings or contact a seller.")
    st.stop()


# --- list view ----------------------------------------------------------------
view = "All listings"
if my_id:
    view = st.radio("View", ["All listings", "⭐ Saved"], horizontal=True)

if view == "⭐ Saved":
    results = filter_and_sort(database.list_favorite_listings(my_id),
                              include_sold=True, sort="newest")
    st.caption(f"{len(results)} saved listing(s)")
    if not results:
        st.info("You haven't saved anything yet. Tap 🤍 on a listing to keep it here.")
else:
    top = st.columns([3, 1])
    with top[0]:
        search = st.text_input("Search", placeholder="e.g. textbook, desk, ticket")
    with top[1]:
        category = st.selectbox("Category", ["All"] + CATEGORIES)

    mid = st.columns([2, 2])
    with mid[0]:
        sort_label = st.selectbox("Sort by", list(SORTS))
    with mid[1]:
        include_sold = st.checkbox("Include sold items", value=False)

    all_listings = database.list_listings(include_sold=True)
    prices = [float(x["price"]) for x in all_listings]
    hi = max(1, int(max(prices))) if prices else 100
    low_sel, high_sel = st.slider("Price range (€)", 0, hi, (0, hi))

    results = filter_and_sort(
        all_listings,
        search=search,
        category=category,
        min_price=low_sel,
        max_price=high_sel,
        include_sold=include_sold,
        sort=SORTS[sort_label],
    )
    st.caption(f"{len(results)} listing(s)")
    if not results:
        st.info("No listings match your filters — try clearing the search, category or price range.")

for item in results:
    with st.container(border=True):
        left, right = st.columns([4, 1])
        with left:
            sold = "" if item["status"] == "available" else " · 🔴 sold"
            st.markdown(f"**{item['title']}** — {price_text(item)}{sold}")
            st.caption(f"{item['category']} · by {item['seller_name']}")
        with right:
            st.button("View", key=f"view_{item['id']}",
                      on_click=open_listing, args=(item["id"],))
            if my_id and my_id != item["seller_id"]:
                is_saved = item["id"] in saved_ids
                st.button("💔" if is_saved else "🤍", key=f"fav_{item['id']}",
                          help="Remove from saved" if is_saved else "Save for later",
                          on_click=toggle_favorite, args=(item["id"],))
