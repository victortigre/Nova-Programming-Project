"""Sales: buyers who asked to buy your items.

A seller sees the requests on each of their listings, accepts one (which reserves
the item and declines the rest), and — once you've met the buyer — confirms you
handed it over. The item is only marked sold when BOTH you and the buyer confirm.
"""

import streamlit as st

import database
import deals
import listings
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


def act(action, request_id: int, done_message: str) -> None:
    """Call a deals.py function, show any error, reload the page on success."""
    try:
        action(database, request_id, email)
    except deals.ListingError as exc:
        for message in exc.errors:
            st.error(message)
    except (deals.NotAllowed, deals.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state["deal_message"] = done_message
        st.rerun()


def request_row(request: dict) -> None:
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
        if request["seller_confirmed_at"]:
            st.markdown(":orange[You confirmed. Waiting for the buyer to confirm too…]")
        else:
            st.markdown(":green[Reserved for this buyer. Meet them, then confirm the hand-over.]")
            if st.button("I handed it over — confirm sold", key=f"sold-{rid}", type="primary"):
                act(deals.confirm_sold, rid,
                    "Confirmed. Once the buyer confirms too, it's marked sold.")
        if st.button("Cancel deal", key=f"cancel-{rid}"):
            act(deals.cancel_deal, rid, "Deal cancelled. The item is active again.")


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
                request_row(request)
except Exception:
    st.info("Buying isn't set up in the database yet. Check back soon.")
    st.stop()

if not shown_any:
    st.info("No buyer requests yet. When someone taps “Request to buy” on one of "
            "your listings, it shows up here.")
    st.page_link("views/my_listings.py", label="See my listings", icon=":material/inventory_2:")
