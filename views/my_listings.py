"""My listings: everything you sell, on one page.

Your own listings are grouped as Active, Reserved and Sold. Each listing is one
card, and everything about it happens inside that card:

- the listing itself: edit, mark as reserved, mark as sold, relist or delete
- buyers who asked through the app: accept or decline, and once you've met the
  buyer, confirm the hand-over (or cancel the deal before that)
- after the sale: who bought it, and rating that buyer

Every button calls a function in listings.py, deals.py or reviews.py, which
checks again that you are the seller before changing anything.

Once a buyer was accepted through the app, that deal decides the status: the
Reserve, Sold, Relist and Delete buttons are hidden until the deal is confirmed
or cancelled (listings.py refuses them too).
"""

import streamlit as st

import database
import deals
import listings
import reviews
import ui
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


def run(action, item_id: int, done_message: str, *extra) -> None:
    """Call a listings.py, deals.py or reviews.py function with a listing id or a
    request id, show any error, reload the page on success."""
    try:
        action(database, item_id, email, *extra)
    except listings.ListingError as exc:
        for message in exc.errors:
            st.error(message)
    except (listings.NotAllowed, listings.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state["listing_message"] = done_message
        st.rerun()


def needs_me(request: dict) -> bool:
    """Is this request waiting for the seller? The same rule as the number in the menu."""
    return request["status"] == deals.REQUESTED


def listing_buttons(listing: dict, has_buyer: bool, waiting: int) -> None:
    """Reserve, Sold, Relist, Edit and Delete. With an accepted buyer: only Edit."""
    lid = listing["id"]
    status = listing["status"]
    buttons = st.columns(5)
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


def request_row(request: dict, price: int) -> None:
    """One buyer who asked for this listing, with the buttons for that deal."""
    rid = request["id"]
    st.divider()
    st.write(f"**{listings.plain_text(request['buyer_name'])}** wants to buy this.")
    if request["status"] == deals.REQUESTED:
        columns = st.columns(2)
        if columns[0].button("Accept", key=f"accept-{rid}", type="primary"):
            run(deals.accept_request, rid, "Accepted. The item is now reserved for this buyer.")
        if columns[1].button("Decline", key=f"decline-{rid}"):
            run(deals.decline_request, rid, "Request declined.")
        return
    # Accepted: the item is reserved for this buyer. The buyer's confirmation
    # finishes the deal; the seller doesn't have to do anything.
    if price:
        st.caption(f"{listings.format_price(price)} is held from the buyer's credits. "
                   "You get it as soon as they confirm they received the item.")
    if request["seller_confirmed_at"]:
        st.markdown(":orange[Handed over. Waiting for the buyer to confirm…]")
        if price and (due := deals.due_text(request)):
            st.caption(f"If the buyer doesn't answer, you get "
                       f"{listings.format_price(price)} automatically on {due}.")
    else:
        st.markdown(":green[Reserved for this buyer. Meet them and hand it over. "
                    "Once they confirm, it's sold.]")
        if st.button("I handed it over", key=f"handed-{rid}",
                     help="Optional. If the buyer forgets to confirm, you are paid "
                          "automatically 48 hours after this."):
            run(deals.confirm_sold, rid,
                "Noted. If the buyer doesn't confirm within 48 hours, you're paid "
                "automatically.")
    # Cancelling is only possible before the hand-over.
    if (not request["seller_confirmed_at"]
            and st.button("Cancel deal", key=f"cancel-{rid}")):
        run(deals.cancel_deal, rid, "Deal cancelled. The item is active again"
            + (" and the buyer got their credits back." if price else "."))


def sale_row(sale: dict) -> None:
    """Who bought this sold listing through the app, and rating that buyer."""
    rid = sale["id"]
    buyer = listings.plain_text(sale["buyer_name"])
    st.divider()
    st.caption(f"Sold to {buyer}")
    if not rating_ready:
        return
    if rid in my_ratings:
        st.caption(f"You rated {buyer} {reviews.star_text(my_ratings[rid]['stars'])}")
        return
    sent = ui.rating_form(rid, "buyer", buyer)
    if sent:
        run(reviews.leave_review, rid, "Thanks for rating!", *sent)


def listing_card(listing: dict) -> None:
    live_requests = live_by_listing.get(listing["id"], [])
    has_buyer = any(r["status"] == deals.ACCEPTED for r in live_requests)
    waiting = sum(1 for r in live_requests if r["status"] == deals.REQUESTED)
    price = listing.get("price_cents") or 0
    with st.container(border=True):
        photo_col, info_col = st.columns([1, 3])
        if listing["photo_paths"]:
            photo_col.image(database.listing_photo_url(listing["photo_paths"][0]))
        info_col.markdown(f"**{listings.plain_text(listing['title'])}**")
        info_col.caption(f"{listings.format_price(listing['price_cents'])} · "
                         f"{listings.plain_text(listings.category_label(listing))} · "
                         f"{listings.plain_text(listings.pickup_label(listing))}")
        if listing["status"] == listings.RESERVED:
            info_col.markdown(":orange[**🔒 Reserved**]")
        with info_col:
            listing_buttons(listing, has_buyer, waiting)
        for request in live_requests:
            request_row(request, price)
        if listing["id"] in sale_by_listing:
            sale_row(sale_by_listing[listing["id"]])


groups = listings.my_listings(database, email)
if not any(groups.values()):
    st.info("You haven't listed anything yet.")
    st.page_link("views/sell_item.py", label="Sell an item", icon="➕")
    st.stop()

# The buyers on all my listings, fetched once for the whole page: the requests
# still open, and the finished sales (for the Sold tab).
try:
    live_by_listing = deals.live_requests_by_listing(database, email)
    sale_by_listing = {sale["listing_id"]: sale for sale in deals.my_sales(database, email)}
except Exception:  # buying isn't set up in the database yet
    live_by_listing, sale_by_listing = {}, {}
try:
    my_ratings = reviews.reviewed_deals(database, email)
    rating_ready = True
except Exception:  # the reviews table isn't in the database yet
    my_ratings, rating_ready = {}, False


def tab_title(status: str) -> str:
    """ "Active (3)", with a bell if a buyer on that tab waits for you."""
    title = f"{status.capitalize()} ({len(groups[status])})"
    waits = any(needs_me(request) for listing in groups[status]
                for request in live_by_listing.get(listing["id"], []))
    return f"{title} 🔔" if waits else title


for tab, status in zip(st.tabs([tab_title(s) for s in listings.STATUSES]), listings.STATUSES):
    with tab:
        if not groups[status]:
            st.caption("Nothing here.")
        for listing in groups[status]:
            listing_card(listing)
