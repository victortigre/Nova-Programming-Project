"""Browse: search the marketplace and save listings — BUYER side (area 3).

Reads the feed and saved listings through database.py; the search and sort rules
live in browsing.py. app.py already lets only verified Nova students in, and we
check again, because the rule is to check where the action happens.
"""

import re

import streamlit as st

import browsing
import database
import listings
from accounts import verified_nova_email

FEED_LIMIT = 500  # the marketplace is small; fetch the newest listings and filter here

email = verified_nova_email(st.user.to_dict())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("Browse")

me = database.get_profile(email)
if me is None:
    st.info("Fill in your profile first. After that you can browse and save items.")
    st.page_link("views/profile.py", label="Fill in my profile")
    st.stop()
my_id = me["id"]

# Saving needs the favorites table. If it isn't in the database yet, the rest of
# Browse still works and saving is quietly turned off with a clear note.
try:
    saved = browsing.saved_ids(database, my_id)
    saving_ready = True
except Exception:
    saved = set()
    saving_ready = False


def plain(text: str) -> str:
    """Show user-written text literally, so a title can't add links or formatting."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>~<$:])", r"\\\1", text or "")


def status_note(status: str) -> str:
    if status == listings.RESERVED:
        return " · :orange[🔒 Reserved]"
    if status == listings.SOLD:
        return " · :red[Sold]"
    return ""


def open_listing(listing_id: int) -> None:
    st.session_state["view_listing"] = listing_id


def close_listing() -> None:
    st.session_state.pop("view_listing", None)


def flip_saved(listing_id: int) -> None:
    browsing.toggle_saved(database, my_id, listing_id)


def save_button(listing_id: int, *, where: str) -> None:
    if not saving_ready:
        return
    is_saved = listing_id in saved
    if where == "detail":
        label = "💔 Remove from saved" if is_saved else "🤍 Save"
    else:
        label = "💔" if is_saved else "🤍"
    st.button(label, key=f"save-{where}-{listing_id}",
              help="Remove from saved" if is_saved else "Save for later",
              on_click=flip_saved, args=(listing_id,))


# --- detail view --------------------------------------------------------------
viewing = st.session_state.get("view_listing")
if viewing is not None:
    item = listings.get_listing(database, viewing)
    if item is None:
        close_listing()
        st.rerun()
    st.button("← Back to results", on_click=close_listing)
    st.subheader(plain(item["title"]))
    st.markdown(f"**{listings.format_price(item['price_cents'])}**{status_note(item['status'])}")
    st.caption(f"{item['category']} · {item['condition']} · {item['pickup_area']}")
    for path in item["photo_paths"]:
        url = database.listing_photo_url(path)
        if url:
            st.image(url, width=320)
    st.write(plain(item["description"]))

    if my_id != item["seller_id"]:
        save_button(item["id"], where="detail")
        st.page_link("views/public_profile.py",
                     label="View the seller's profile to get in touch",
                     query_params={"id": item["seller_id"]})
    else:
        st.caption("This is your own listing.")
    st.stop()


# --- a card in the results ----------------------------------------------------
def listing_card(item: dict) -> None:
    with st.container(border=True):
        photo_col, info_col = st.columns([1, 3])
        cover = item["photo_paths"][0] if item["photo_paths"] else None
        url = database.listing_photo_url(cover) if cover else None
        if url:
            photo_col.image(url)
        else:
            photo_col.markdown("### 🛍️")
        info_col.markdown(f"**{plain(item['title'])}** — "
                          f"{listings.format_price(item['price_cents'])}{status_note(item['status'])}")
        info_col.caption(f"{item['category']} · {item['pickup_area']}")
        actions = info_col.columns([1, 1, 4])
        actions[0].button("View", key=f"view-{item['id']}",
                          on_click=open_listing, args=(item["id"],))
        if my_id != item["seller_id"]:
            with actions[1]:
                save_button(item["id"], where="card")


# --- Browse and Saved tabs ----------------------------------------------------
browse_tab, saved_tab = st.tabs(["Browse", f"⭐ Saved ({len(saved)})"])

with browse_tab:
    feed = listings.feed_listings(database, limit=FEED_LIMIT)

    top = st.columns([3, 1])
    query = top[0].text_input("Search", placeholder="e.g. calculator, desk, bike")
    category = top[1].selectbox("Category", ["All"] + listings.CATEGORIES)

    row = st.columns([2, 2])
    sort_label = row[0].selectbox("Sort by", list(browsing.SORTS))
    max_euros = max((item["price_cents"] // 100 for item in feed), default=0)
    if max_euros < 1:
        max_euros = 100
    low, high = row[1].slider("Price (€)", 0, max_euros, (0, max_euros))

    results = browsing.search_and_sort(
        feed, query=query, category=category,
        min_cents=low * 100, max_cents=high * 100,
        sort=browsing.SORTS[sort_label],
    )
    st.caption(f"{len(results)} listing(s)")
    if not results:
        st.info("No listings match your filters — try clearing the search, category or price range.")
    for item in results:
        listing_card(item)

with saved_tab:
    if not saving_ready:
        st.info("Saving isn't set up in the database yet. Whoever manages the database "
                "needs to run `database_setup.sql` (it adds the favorites table).")
    else:
        saved_items = browsing.saved_listings(database, my_id)
        if not saved_items:
            st.info("You haven't saved anything yet. Tap 🤍 on a listing to keep it here.")
        for item in saved_items:
            listing_card(item)
