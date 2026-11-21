"""My purchases: the items you've asked to buy, and confirming you received them.

A buyer sees every deal they're in, cancels a request, and — once the seller has
accepted and you've met — confirms you received the item. The item is only marked
sold when BOTH you and the seller have confirmed. After that, you rate the seller.
Requests that ended without a sale (declined, cancelled) stay visible under
"Closed", so a buyer always learns what happened.
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

st.header("My purchases")

if database.get_profile(email) is None:
    st.info("Fill in your profile first. After that you can buy items.")
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

try:
    my_ratings = reviews.reviewed_deals(database, email)
    rating_ready = True
except Exception:  # the reviews table isn't in the database yet
    my_ratings, rating_ready = {}, False


def rate_the_seller(request_id: int, seller_name: str) -> None:
    """1 to 5 stars and optional feedback for a completed deal, or the rating already given."""
    if not rating_ready:
        return
    if request_id in my_ratings:
        st.caption(f"You rated {seller_name} {reviews.star_text(my_ratings[request_id]['stars'])}")
        return
    sent = ui.rating_form(request_id, "seller", seller_name)
    if sent:
        act(reviews.leave_review, request_id, "Thanks for rating!", *sent)


CLOSED = (deals.DECLINED, deals.CANCELLED)
open_deals = [deal for deal in purchases if deal["status"] not in CLOSED]
closed_deals = [deal for deal in purchases if deal["status"] in CLOSED]
if not open_deals:
    st.caption("Nothing in progress right now.")


def show_deal(deal: dict) -> None:
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

        price = listing.get("price_cents") or 0
        if status == deals.REQUESTED:
            st.markdown(":grey[Waiting for the seller to accept your request…]")
            if price:
                st.caption(f"When the seller accepts, {listings.format_price(price)} "
                           "is held from your Nova credits.")
            if st.button("Cancel request", key=f"cancel-{request_id}"):
                act(deals.cancel_deal, request_id, "Request cancelled.")

        elif status == deals.ACCEPTED:
            if deal["buyer_confirmed_at"]:
                st.markdown(":orange[You confirmed. Waiting for the seller to confirm too…]")
                if price:
                    st.caption(f"{listings.format_price(price)} went to the seller.")
            elif deal.get("seller_confirmed_at"):
                # Handed over: 48 hours to confirm. No cancelling any more.
                st.warning(f"The seller says they handed it over. Check the item and confirm "
                           f"by **{deals.due_text(deal)}**. After that, the payment goes to "
                           "the seller automatically.",
                           icon=":material/schedule:")
                if st.button("I received it, all OK", key=f"recv-{request_id}",
                             type="primary"):
                    act(deals.confirm_received, request_id,
                        "Thanks! " + (f"{listings.format_price(price)} went to the seller."
                                      if price else "Enjoy!"))
            else:
                st.markdown(":green[Accepted! Meet the seller to collect it, then confirm below.]")
                if price:
                    st.caption(f"{listings.format_price(price)} is held from your credits. "
                               "Confirming sends it to the seller, so only confirm once "
                               "you have the item.")
                if st.button("I received the item", key=f"recv-{request_id}", type="primary"):
                    act(deals.confirm_received, request_id,
                        "Thanks! Waiting for the seller to confirm too.")
            if listing.get("seller_id"):
                st.page_link("views/public_profile.py", label="View the seller's profile",
                             icon=":material/person:", query_params={"id": listing["seller_id"]})
            # Cancelling is only possible before the hand-over.
            if (not deal["buyer_confirmed_at"] and not deal.get("seller_confirmed_at")
                    and st.button("Cancel deal", key=f"cancel-{request_id}")):
                act(deals.cancel_deal, request_id,
                    "Deal cancelled." + (" Your credits are back." if price else ""))

        elif status == deals.COMPLETED:
            st.markdown(":green[✅ Done — both of you confirmed. Enjoy!]")
            rate_the_seller(request_id, listings.plain_text(seller["name"]) if seller
                            else "the seller")

        elif status == deals.DECLINED:
            st.markdown(":grey[The seller said no, or chose another buyer.]")

        elif status == deals.CANCELLED:
            st.markdown(":grey[This deal was cancelled.]")


for deal in open_deals:
    show_deal(deal)

if closed_deals:
    with st.expander(f"Closed ({len(closed_deals)})"):
        for deal in closed_deals:
            show_deal(deal)
