"""My purchases: the items you've asked to buy, and confirming you received them.

A buyer sees every deal they're in, cancels a request, and — once the seller has
accepted and you've met — confirms you received the item. The item is only marked
sold when BOTH you and the seller have confirmed.
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

st.header("My purchases")

if database.get_profile(email) is None:
    st.info("Fill in your profile first. After that you can buy items.")
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


try:
    purchases = deals.my_purchases(database, email)
except (deals.ListingError, deals.NotAllowed, deals.NotFound):
    raise
except Exception:
    st.info("Buying isn't set up in the database yet. Check back soon.")
    st.stop()

if not purchases:
    st.info("You haven't asked to buy anything yet. "
            "Find something on Browse and tap “Request to buy”.")
    st.page_link("views/browse.py", label="Browse items", icon=":material/search:")
    st.stop()

for deal in purchases:
    listing = deal["listing"] or {}
    request_id = deal["id"]
    status = deal["status"]
    with st.container(border=True):
        title = listings.plain_text(listing.get("title", "(this listing was removed)"))
        st.markdown(f"**{title}** · {listings.format_price(listing.get('price_cents', 0))}")
        seller = (database.get_profile_by_id(listing["seller_id"])
                  if listing.get("seller_id") else None)
        if seller:
            st.caption(f"Seller: {listings.plain_text(seller['name'])}")

        if status == deals.REQUESTED:
            st.markdown(":grey[Waiting for the seller to accept your request…]")
            if st.button("Cancel request", key=f"cancel-{request_id}"):
                act(deals.cancel_deal, request_id, "Request cancelled.")

        elif status == deals.ACCEPTED:
            if deal["buyer_confirmed_at"]:
                st.markdown(":orange[You confirmed. Waiting for the seller to confirm too…]")
            else:
                st.markdown(":green[Accepted! Meet the seller to collect it, then confirm below.]")
                if st.button("I received the item", key=f"recv-{request_id}", type="primary"):
                    act(deals.confirm_received, request_id,
                        "Thanks! Waiting for the seller to confirm too.")
            if listing.get("seller_id"):
                st.page_link("views/public_profile.py", label="View the seller's profile",
                             icon=":material/person:", query_params={"id": listing["seller_id"]})
            if st.button("Cancel deal", key=f"cancel-{request_id}"):
                act(deals.cancel_deal, request_id, "Deal cancelled.")

        elif status == deals.COMPLETED:
            st.markdown(":green[✅ Done — both of you confirmed. Enjoy!]")
