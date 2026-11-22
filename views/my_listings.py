"""My listings: everything you sell, on one page.

Your own listings are grouped as Active, Reserved and Sold. Each listing is one
card, and everything about it happens inside that card:

- the listing itself: edit, mark as reserved, mark as sold, relist or delete
- a buyer who tapped Buy Now: wait for their payment (or cash when you meet), then
  confirm the payment arrived (or say it didn't, or cancel the sale)
- after the sale: who bought it, and rating that buyer

Every button calls a function in listings.py, deals.py or reviews.py, which
checks again that you are the seller before changing anything.

Once a buyer tapped Buy Now, that deal decides the status: the
Reserve, Sold, Relist and Delete buttons are hidden until the deal is confirmed
or cancelled (listings.py refuses them too).
"""

import streamlit as st

import database
import deals
import listings
import payment_ui
import payments
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
payment_ui.show_message()


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
    return request["status"] == deals.REQUESTED or bool(
        request["status"] == deals.ACCEPTED and request.get("paid_at"))


def listing_buttons(listing: dict, has_buyer: bool, waiting: int,
                    sold_in_app: bool = False) -> None:
    """Reserve, Sold, Relist, Edit and Delete. With an accepted buyer: only Edit.
    Sold through the app: no Delete, the sale stays as a record for both sides."""
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
    # listings.delete_listing refuses this too; here the button is simply not shown.
    if sold_in_app:
        return
    with buttons[4].popover("Delete"):
        st.write("Delete this listing for good?")
        if st.button("Yes, delete", key=f"delete-{lid}", type="primary"):
            run(listings.delete_listing, lid, "Listing deleted.")


def request_row(request: dict, price: int) -> None:
    """One buyer of this listing, with the payment box for that deal."""
    rid = request["id"]
    st.divider()
    if request["status"] == deals.REQUESTED:
        # An old "Request to buy" from before Buy Now: it can only be declined.
        st.write(f"**{listings.plain_text(request['buyer_name'])}** asked to buy this "
                 "(old request). Buying now works through the chat.")
        if st.button("Decline", key=f"decline-{rid}"):
            run(deals.decline_request, rid, "Request declined.")
        return
    st.write(f"**{listings.plain_text(request['buyer_name'])}** is buying this.")
    payment_ui.seller_box(request, email, where="mylistings",
                          buyer_name=request["buyer_name"])


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
            listing_buttons(listing, has_buyer, waiting,
                            sold_in_app=listing["id"] in sale_by_listing)
        for request in live_requests:
            request_row(request, price)
        if listing["id"] in sale_by_listing:
            sale_row(sale_by_listing[listing["id"]])


groups = listings.my_listings(database, email)
# Selling for money needs a way to get paid (payments.py, deals.py).
if (not payments.can_be_paid(database.get_profile(email))
        and any(item.get("price_cents") for item in groups[listings.ACTIVE])):
    st.warning("Buyers can't buy your items until you add a way to get paid on My profile.",
               icon=":material/account_balance:")
    st.page_link("views/profile.py", label="Add how I get paid",
                 icon=":material/account_balance:")
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
