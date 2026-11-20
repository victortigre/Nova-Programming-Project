"""My listings: all your own listings, grouped as Active, Reserved and Sold.

From here a seller can edit, mark as reserved, mark as sold, relist or delete.
Every button calls a function in listings.py, which checks again that you
are the seller before changing anything.

Once a buyer was accepted through the app, that deal decides the status: the
Reserve, Sold, Relist and Delete buttons are hidden and the seller goes to
Sales instead (listings.py refuses them too).
"""

import streamlit as st

import database
import deals
import listings
from accounts import logged_in_user, verified_nova_email

# Who is using this page? The email always comes from the login, never from a form.
email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("My listings")

if database.get_profile(email) is None:
    st.info("Fill in your profile first. After that you can sell items.")
    st.page_link("views/profile.py", label="Fill in my profile")
    st.stop()

# A message from the last button press survives the page reload.
if "listing_message" in st.session_state:
    st.success(st.session_state.pop("listing_message"))


def run(action, listing_id: int, done_message: str) -> None:
    """Call a listings.py function, show any error, reload the page on success."""
    try:
        action(database, listing_id, email)
    except listings.ListingError as exc:
        for message in exc.errors:
            st.error(message)
    except (listings.NotAllowed, listings.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state["listing_message"] = done_message
        st.rerun()


def listing_row(listing: dict, live_requests: list[dict]) -> None:
    lid = listing["id"]
    status = listing["status"]
    has_buyer = any(r["status"] == deals.ACCEPTED for r in live_requests)
    waiting = sum(1 for r in live_requests if r["status"] == deals.REQUESTED)
    with st.container(border=True):
        photo_col, info_col = st.columns([1, 3])
        if listing["photo_paths"]:
            photo_col.image(database.listing_photo_url(listing["photo_paths"][0]))
        info_col.markdown(f"**{listings.plain_text(listing['title'])}**")
        info_col.caption(f"{listings.format_price(listing['price_cents'])} · "
                         f"{listings.plain_text(listings.category_label(listing))} · "
                         f"{listings.plain_text(listings.pickup_label(listing))}")
        if until := listings.available_label(listing):
            info_col.caption(until)
        if status != listings.SOLD and listings.is_expired(listing):
            info_col.markdown(":red[**Expired: buyers no longer see this.** "
                              "Edit it to choose a new date.]")
        if status == listings.RESERVED:
            info_col.markdown(":orange[**🔒 Reserved**]")
        if has_buyer or waiting:
            if has_buyer:
                info_col.caption("🤝 Reserved for a buyer who asked through the app. "
                                 "Confirm or cancel the deal on Sales.")
            else:
                info_col.caption(f"🔔 {waiting} buyer request{'s' if waiting != 1 else ''} "
                                 "waiting for your answer.")
            info_col.page_link("views/sales.py", label="Open Sales", icon=":material/sell:")

        buttons = info_col.columns(5)
        if has_buyer:
            if buttons[0].button("Edit", key=f"edit-{lid}"):
                st.session_state["edit_listing_id"] = lid
                st.switch_page("views/sell_item.py")
            return
        # Reserving or selling outside the app says "no" to the buyers still waiting.
        no_to_waiting = (f"The {waiting} waiting request{'s' if waiting != 1 else ''} "
                         "will be declined.") if waiting else None
        if status == listings.ACTIVE and buttons[0].button("Reserve", key=f"reserve-{lid}",
                                                            help=no_to_waiting):
            run(listings.mark_reserved, lid, "Marked as reserved.")
        if status != listings.SOLD and buttons[1].button("Sold", key=f"sold-{lid}",
                                                          help=no_to_waiting):
            run(listings.mark_sold, lid, "Marked as sold. It no longer shows in the marketplace.")
        if status != listings.ACTIVE and buttons[2].button("Relist", key=f"relist-{lid}"):
            run(listings.relist, lid, "Back on the marketplace.")
        if buttons[3].button("Edit", key=f"edit-{lid}"):
            st.session_state["edit_listing_id"] = lid
            st.switch_page("views/sell_item.py")
        with buttons[4].popover("Delete"):
            st.write("Delete this listing for good?")
            if st.button("Yes, delete", key=f"delete-{lid}", type="primary"):
                run(listings.delete_listing, lid, "Listing deleted.")


groups = listings.my_listings(database, email)
# The live requests on all my listings, fetched once for the whole page.
try:
    live_by_listing = deals.live_requests_by_listing(database, email)
except Exception:  # buying isn't set up in the database yet
    live_by_listing = {}

if not any(groups.values()):
    st.info("You haven't listed anything yet.")
    st.page_link("views/sell_item.py", label="Sell an item", icon="➕")
    st.stop()

tab_titles = [f"Active ({len(groups[listings.ACTIVE])})",
              f"Reserved ({len(groups[listings.RESERVED])})",
              f"Sold ({len(groups[listings.SOLD])})"]
for tab, status in zip(st.tabs(tab_titles), listings.STATUSES):
    with tab:
        if not groups[status]:
            st.caption("Nothing here.")
        for listing in groups[status]:
            listing_row(listing, live_by_listing.get(listing["id"], []))
