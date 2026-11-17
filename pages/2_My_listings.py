"""My listings: all your own listings, grouped as Active, Reserved and Sold.

From here a seller can edit, mark as reserved, mark as sold, relist or delete.
Every button calls a function in listings.py, which checks again that you
are the seller before changing anything.
"""

import re

import streamlit as st

import listings
from seller_login import require_nova_student

st.set_page_config(page_title="My listings · Nova Marketplace", page_icon="📦")

me = require_nova_student()
conn = listings.connect()

st.title("My listings")

# A message from the last button press survives the page reload.
if "listing_message" in st.session_state:
    st.success(st.session_state.pop("listing_message"))


def plain(text: str) -> str:
    """Show user-written text literally, so a title can't add links or formatting."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>~<$:])", r"\\\1", text)


def run(action, listing_id: int, done_message: str) -> None:
    """Call a listings.py function, show any error, reload the page on success."""
    try:
        action(conn, listing_id, me["email"])
    except listings.ListingError as exc:
        for message in exc.errors:
            st.error(message)
    except (listings.NotAllowed, listings.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state["listing_message"] = done_message
        st.rerun()


def listing_row(listing: dict) -> None:
    lid = listing["id"]
    status = listing["status"]
    with st.container(border=True):
        photo_col, info_col = st.columns([1, 3])
        if listing["cover"]:
            photo_col.image(listing["cover"])
        info_col.markdown(f"**{plain(listing['title'])}**")
        info_col.caption(f"{listings.format_price(listing['price_cents'])} · "
                         f"{listing['category']} · {listing['pickup_area']}")
        if status == listings.RESERVED:
            info_col.markdown(":orange[**🔒 Reserved**]")

        buttons = info_col.columns(5)
        if status == listings.ACTIVE and buttons[0].button("Reserve", key=f"reserve-{lid}"):
            run(listings.mark_reserved, lid, "Marked as reserved.")
        if status != listings.SOLD and buttons[1].button("Sold", key=f"sold-{lid}"):
            run(listings.mark_sold, lid, "Marked as sold. It no longer shows in the marketplace.")
        if status != listings.ACTIVE and buttons[2].button("Relist", key=f"relist-{lid}"):
            run(listings.relist, lid, "Back on the marketplace.")
        if buttons[3].button("Edit", key=f"edit-{lid}"):
            st.session_state["edit_listing_id"] = lid
            st.switch_page("pages/1_Sell_an_item.py")
        with buttons[4].popover("Delete"):
            st.write("Delete this listing for good?")
            if st.button("Yes, delete", key=f"delete-{lid}", type="primary"):
                run(listings.delete_listing, lid, "Listing deleted.")


groups = listings.my_listings(conn, me["email"])

if not any(groups.values()):
    st.info("You haven't listed anything yet.")
    st.page_link("pages/1_Sell_an_item.py", label="Sell an item", icon="➕")
    st.stop()

tab_titles = [f"Active ({len(groups[listings.ACTIVE])})",
              f"Reserved ({len(groups[listings.RESERVED])})",
              f"Sold ({len(groups[listings.SOLD])})"]
for tab, status in zip(st.tabs(tab_titles), listings.STATUSES):
    with tab:
        if not groups[status]:
            st.caption("Nothing here.")
        for listing in groups[status]:
            listing_row(listing)
