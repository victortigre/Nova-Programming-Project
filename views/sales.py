"""Sales: buyers who asked to buy your items.

A seller sees the requests on each of their listings, accepts one (which reserves
the item and declines the rest), and — once you've met the buyer — confirms you
handed it over. The item is only marked sold when BOTH you and the buyer confirm.
Below that, "Completed sales" lists what you sold, where you rate each buyer.
"""

import streamlit as st

import database
import deals
import listings
import reviews
import ui
from accounts import logged_in_user, verified_nova_email

email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("Sales")

if database.get_profile(email) is None:
    st.info("Fill in your profile first. After that you can sell items.")
    st.page_link("views/profile.py", label="Fill in my profile")
    st.stop()

if "deal_message" in st.session_state:
    st.success(st.session_state.pop("deal_message"))


def act(action, request_id: int, done_message: str, *extra) -> None:
    """Call a deals.py or reviews.py function, show any error, reload on success."""
    try:
        action(database, request_id, email, *extra)
    except deals.ListingError as exc:
        for message in exc.errors:
            st.error(message)
    except (deals.NotAllowed, deals.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state["deal_message"] = done_message
        st.rerun()


def request_row(request: dict, price: int = 0) -> None:
    rid = request["id"]
    st.divider()
    st.write(f"**{request['buyer_name']}** wants to buy this.")
    if request["status"] == deals.REQUESTED:
        columns = st.columns(2)
        if columns[0].button("Accept", key=f"accept-{rid}", type="primary"):
            act(deals.accept_request, rid, "Accepted. The item is now reserved for this buyer.")
        if columns[1].button("Decline", key=f"decline-{rid}"):
            act(deals.decline_request, rid, "Request declined.")
    elif request["status"] == deals.ACCEPTED:
        if request["buyer_confirmed_at"] and price:
            st.caption(f"The buyer confirmed they got it: {listings.format_price(price)} "
                       "is in your Nova credits.")
        elif price:
            st.caption(f"{listings.format_price(price)} is held from the buyer's credits. "
                       "You get it when they confirm they received the item.")
        if request["seller_confirmed_at"]:
            st.markdown(":orange[You confirmed. Waiting for the buyer to confirm too…]")
            if price and (due := deals.due_text(request)):
                st.caption(f"If the buyer doesn't answer, you get "
                           f"{listings.format_price(price)} automatically on {due}.")
        else:
            st.markdown(":green[Reserved for this buyer. Meet them, then confirm the hand-over.]")
            if st.button("I handed it over — confirm sold", key=f"sold-{rid}", type="primary"):
                act(deals.confirm_sold, rid,
                    "Confirmed. Once the buyer confirms too, it's marked sold.")
        # Cancelling is only possible before the hand-over.
        if (not request["buyer_confirmed_at"] and not request["seller_confirmed_at"]
                and st.button("Cancel deal", key=f"cancel-{rid}")):
            act(deals.cancel_deal, rid, "Deal cancelled. The item is active again"
                + (" and the buyer got their credits back." if price else "."))


# Only active/reserved listings can have live requests.
groups = listings.my_listings(database, email)
sellable = groups[listings.ACTIVE] + groups[listings.RESERVED]

shown_any = False
try:
    for listing in sellable:
        requests = deals.requests_on_listing(database, listing["id"], email, statuses=deals.LIVE)
        if not requests:
            continue
        shown_any = True
        with st.container(border=True):
            st.markdown(f"### {listings.plain_text(listing['title'])}")
            st.caption(f"{listings.format_price(listing['price_cents'])} · {listing['status']}")
            for request in requests:
                request_row(request, listing.get("price_cents") or 0)
except Exception:
    st.info("Buying isn't set up in the database yet. Check back soon.")
    st.stop()

if not shown_any:
    st.info("No buyer requests right now. When someone taps “Request to buy” on one of "
            "your listings, it shows up here.")
    st.page_link("views/my_listings.py", label="See my listings", icon=":material/inventory_2:")


# --- Completed sales: what you sold, and rating each buyer ---------------------
completed = deals.my_sales(database, email)
try:
    my_ratings = reviews.reviewed_deals(database, email)
    rating_ready = True
except Exception:  # the reviews table isn't in the database yet
    my_ratings, rating_ready = {}, False

if completed:
    st.subheader(f"Completed sales ({len(completed)})")
for sale in completed:
    rid = sale["id"]
    with st.container(border=True):
        st.markdown(f"**{listings.plain_text(sale['title'])}** · "
                    f"{listings.format_price(sale['price_cents'])}")
        st.caption(f"Sold to {listings.plain_text(sale['buyer_name'])}")
        if not rating_ready:
            continue
        if rid in my_ratings:
            st.caption(f"You rated {listings.plain_text(sale['buyer_name'])} "
                       f"{reviews.star_text(my_ratings[rid]['stars'])}")
            continue
        sent = ui.rating_form(rid, "buyer", listings.plain_text(sale["buyer_name"]))
        if sent:
            act(reviews.leave_review, rid, "Thanks for rating!", *sent)
