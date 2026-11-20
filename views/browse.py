"""Browse: search the marketplace and save listings — BUYER side (area 3).

Reads the feed and saved listings through database.py; the search and sort rules
live in browsing.py. app.py already lets only verified Nova students in, and we
check again, because the rule is to check where the action happens.
"""

import re
from functools import partial

import streamlit as st

import browsing
import database
import deals
import listings
import ui
from accounts import verified_nova_email

FEED_LIMIT = 500  # the marketplace is small; fetch the newest listings and filter here

email = verified_nova_email(st.user.to_dict())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

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
        label = "♥ Saved" if is_saved else "♡ Save"
    else:
        label = "♥" if is_saved else "♡"
    st.button(label, key=f"save-{where}-{listing_id}",
              help="Remove from saved" if is_saved else "Save for later",
              on_click=flip_saved, args=(listing_id,))


# --- detail view --------------------------------------------------------------
# Another page (a student's profile) can ask Browse to open one listing.
if "open_listing" in st.session_state:
    st.session_state["view_listing"] = st.session_state.pop("open_listing")
viewing = st.session_state.get("view_listing")
if viewing is not None:
    item = listings.get_listing(database, viewing)
    if item is None:
        close_listing()
        st.rerun()
    st.button("Back to results", icon=":material/arrow_back:", type="tertiary",
              on_click=close_listing)
    with ui.card("detail"):
        photo_col, info_col = st.columns([1, 1], gap="large")
        with photo_col:
            links = database.listing_photo_urls(item["photo_paths"])
            urls = [links[path] for path in item["photo_paths"] if path in links]
            if urls:
                st.image(urls[0], width="stretch")
                if len(urls) > 1:
                    for column, url in zip(st.columns(4), urls[1:5]):
                        column.image(url, width="stretch")
            else:
                st.html('<div class="nm-photo"><span class="nm-empty">🛍️</span></div>')
        with info_col:
            st.subheader(plain(item["title"]))
            st.html(f'<p class="nm-price">{listings.format_price(item["price_cents"])}</p>')
            if item["status"] != listings.ACTIVE:
                st.markdown(status_note(item["status"]).lstrip(" ·"))
            st.html(ui.chip(listings.category_label(item)) + ui.chip(item["condition"])
                    + ui.chip(listings.pickup_label(item), warm=True))
            seller = database.get_profile_by_id(item["seller_id"])
            if seller and my_id != item["seller_id"]:
                st.markdown(f"Sold by **{plain(seller['name'])}**")
            st.write(plain(item["description"]))
            if message := st.session_state.pop("deal_message", None):
                st.success(message)
            if error := st.session_state.pop("deal_error", None):
                st.error(error)
            if my_id != item["seller_id"]:
                if item["status"] == listings.ACTIVE:
                    if st.button("Request to buy", key=f"buy-{item['id']}",
                                 type="primary", icon=":material/shopping_bag:"):
                        try:
                            deals.request_to_buy(database, item["id"], email)
                            st.session_state["deal_message"] = (
                                "Request sent! Track it in My purchases.")
                        except (deals.ListingError, deals.NotAllowed, deals.NotFound) as exc:
                            st.session_state["deal_error"] = (
                                exc.errors[0] if isinstance(exc, deals.ListingError) else str(exc))
                        except Exception:
                            st.session_state["deal_error"] = (
                                "Buying isn't set up yet. Please try again later.")
                        st.rerun()
                elif item["status"] == listings.RESERVED:
                    st.caption("This item is reserved for another buyer.")
                save_button(item["id"], where="detail")
                st.page_link("views/public_profile.py",
                             label="View the seller's profile to get in touch",
                             icon=":material/person:",
                             query_params={"id": item["seller_id"]})
                st.page_link("views/report.py", label="Report this listing",
                             icon=":material/flag:", query_params={"listing": item["id"]})
            else:
                st.caption("This is your own listing.")
    st.stop()


# --- the grid of results -----------------------------------------------------
# A saved listing shows up in both tabs, so "tab" goes into each key:
# Streamlit refuses two buttons with the same key on one page.
def listing_grid(items: list[dict], tab: str, columns: int = 3) -> None:
    # One request for all cover photo links, instead of one per card.
    links = database.listing_photo_urls(
        [item["photo_paths"][0] for item in items if item["photo_paths"]])
    for start in range(0, len(items), columns):
        row = st.columns(columns, gap="medium")
        for column, item in zip(row, items[start:start + columns]):
            cover = item["photo_paths"][0] if item["photo_paths"] else None
            with column:
                own = my_id == item["seller_id"]
                clicked = ui.listing_card(
                    item,
                    links.get(cover),
                    key=f"{tab}-{item['id']}",
                    saved=None if (own or not saving_ready) else item["id"] in saved,
                    on_heart=partial(flip_saved, item["id"]),
                )
            if clicked:
                open_listing(item["id"])
                st.rerun()


# --- What needs your attention ------------------------------------------------
# The same numbers as in the menu ("Sales (2)"), spelled out, with a link.
def plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


try:
    to_do = deals.to_do(database, email)
except Exception:  # buying isn't set up in the database yet
    to_do = {"answer": 0, "confirm_sale": 0, "confirm_received": 0}
if to_do["answer"]:
    with st.container(border=True):
        st.markdown(f"🔔 **{plural(to_do['answer'], 'buyer wants', 'buyers want')} "
                    "to buy your items.** Accept or decline on Sales.")
        st.page_link("views/sales.py", label="Open Sales", icon=":material/sell:")
if to_do["confirm_sale"]:
    with st.container(border=True):
        st.markdown(f"🔔 **{plural(to_do['confirm_sale'], 'buyer', 'buyers')} confirmed "
                    "they got the item.** Confirm the hand-over too, so it counts as sold.")
        st.page_link("views/sales.py", label="Open Sales", icon=":material/sell:")
if to_do["confirm_received"]:
    with st.container(border=True):
        st.markdown(f"🔔 **{plural(to_do['confirm_received'], 'seller', 'sellers')} "
                    "accepted your request.** Meet them, then confirm you got the item.")
        st.page_link("views/purchases.py", label="Open My purchases",
                     icon=":material/shopping_bag:")


# --- Browse and Saved tabs ----------------------------------------------------
browse_tab, saved_tab = st.tabs(["All items", f"♥ Saved ({len(saved)})"])

with browse_tab:
    query = st.text_input("Search", placeholder="Search desks, books, bikes...",
                          icon=":material/search:", label_visibility="collapsed")
    category = st.pills("Category", ["All"] + listings.CATEGORIES, default="All",
                        label_visibility="collapsed") or "All"
    feed = listings.feed_listings(database, limit=FEED_LIMIT)
    filters_col, grid_col = st.columns([1, 3], gap="medium")

    with filters_col:
        prices = [item["price_cents"] / 100 for item in feed]
        # Always €0 to the highest price a listing may have (€1,000), so the
        # range is the same for everyone, whatever is on sale right now.
        max_euros = listings.MAX_PRICE_CENTS // 100
        with ui.card("price-range"):
            st.markdown("**Price range**")
            if prices:
                st.caption(f"The average price is €{sum(prices) / len(prices):,.0f}")
            ui.price_chart(prices)
            low, high = st.slider("Price (€)", 0, max_euros, (0, max_euros), step=5,
                                  format="€%d", label_visibility="collapsed")
        with ui.card("location"):
            st.markdown("**Location**")
            st.caption("Where you can pick it up. Choose none to see all.")
            pickup_areas = st.pills("Location", listings.PICKUP_AREAS, selection_mode="multi",
                                    default=[], label_visibility="collapsed")
        with ui.card("condition"):
            st.markdown("**Condition**")
            st.caption("Choose none to see all.")
            conditions = st.pills("Condition", listings.CONDITIONS, selection_mode="multi",
                                  default=[], label_visibility="collapsed")
        with ui.card("sort"):
            st.markdown("**Sort by**")
            sort_label = st.radio("Sort by", list(browsing.SORTS),
                                  label_visibility="collapsed")

    results = browsing.search_and_sort(
        feed, query=query, category=category,
        min_cents=low * 100, max_cents=high * 100,
        conditions=conditions, pickup_areas=pickup_areas,
        sort=browsing.SORTS[sort_label],
    )
    with grid_col:
        st.caption(f"{len(results)} listing(s)")
        if not results:
            st.info("No listings match your filters. Try clearing the search, "
                    "category, price range, location or condition.")
        listing_grid(results, tab="browse")

with saved_tab:
    if not saving_ready:
        st.info("Saving isn't set up in the database yet. Whoever manages the database "
                "needs to run `database_setup.sql` (it adds the favorites table).")
    else:
        saved_items = browsing.saved_listings(database, my_id)
        if not saved_items:
            st.info("You haven't saved anything yet. Tap ♡ on a listing to keep it here.")
        listing_grid(saved_items, tab="saved", columns=4)
