"""My purchases: the items you're buying, and paying the seller for them.

After "Buy Now", the buyer sees how to pay (the seller's IBAN, or cash in
person) and has 48 hours to pay and tap "I've paid" (cash: when
they meet, no deadline). When the seller confirms the money
arrived, the item is sold and the buyer can rate the seller. Purchases that
ended without a sale (cancelled) stay visible under "Closed".
"""

import streamlit as st

import database
import deals
import listings
import reviews
import payment_ui
import ui
from accounts import logged_in_user, verified_nova_email

email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("My purchases")
st.html("""<style>
[class*="st-key-purchase-main-card-"] { background-color: #FFFFFF; }
[class*="st-key-purchase-main-card-"] > [data-testid="stHorizontalBlock"] { align-items: flex-start; gap: 16px; }
[class*="st-key-purchase-main-card-"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {
    flex: 0 0 136px !important; min-width: 0;
}
[class*="st-key-purchase-main-card-"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {
    flex: 1 1 0 !important; min-width: 0;
}
[class*="st-key-purchase-thumbnail-"] img {
    width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 10px;
}
[class*="st-key-purchase-thumbnail-"] .listing-photo-placeholder {
    width: 100%; aspect-ratio: 4 / 3; border-radius: 10px; background: #F1F2F6;
    display: grid; place-items: center; color: #737985;
}
@media (max-width: 700px) {
    [class*="st-key-purchase-main-card-"] > [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
    [class*="st-key-purchase-main-card-"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {
        flex-basis: 104px !important;
    }
    [class*="st-key-purchase-main-card-"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {
        flex: 1 1 240px !important; max-width: 100%;
    }
}
</style>""")

if database.get_profile(email) is None:
    st.info("Fill in your profile first. After that you can buy items.")
    st.page_link("views/profile.py", label="Fill in my profile")
    st.stop()

if "deal_message" in st.session_state:
    st.success(st.session_state.pop("deal_message"))
payment_ui.show_message()


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
    st.info("You haven't bought anything yet. Find something on Browse, agree a price "
            "with the seller in the chat, and tap “Buy Now”.")
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
    with st.container(border=True, key=f"purchase-main-card-{request_id}"):
        photo_col, info_col = st.columns([1, 5], gap="medium", vertical_alignment="top")
        with photo_col:
            with st.container(key=f"purchase-thumbnail-{request_id}"):
                paths = listing.get("photo_paths") or []
                try:
                    photo_url = database.listing_photo_url(paths[0]) if paths else None
                except Exception:
                    photo_url = None  # Optional images must not hide purchase controls.
                if photo_url:
                    st.image(photo_url, width="stretch")
                else:
                    st.html('<div class="listing-photo-placeholder" role="img" aria-label="Listing photo unavailable">🛍️</div>')
        with info_col:
            title = listings.plain_text(listing.get("title", "(this listing was removed)"))
            st.markdown(f"**{title}** · {listings.format_price(deals.price_of(deal, listing))}")
            # The name came along with the deals (deals.my_purchases), so showing
            # it needs no extra request per deal.
            seller_name = deal.get("seller_name")
            if seller_name:
                st.caption(f"Seller: {listings.plain_text(seller_name)}")

            if status == deals.REQUESTED:
                # An old "Request to buy" from before Buy Now.
                st.markdown(":grey[Waiting for the seller to answer your request…]")
                if st.button("Cancel request", key=f"cancel-{request_id}"):
                    act(deals.cancel_deal, request_id, "Request cancelled.")

            elif status == deals.ACCEPTED:
                payment_ui.buyer_box(deal, email, where="purchases")
                if listing.get("seller_id"):
                    st.page_link("views/public_profile.py", label="View the seller's profile",
                                 icon=":material/person:", query_params={"id": listing["seller_id"]})

            elif status == deals.COMPLETED:
                st.markdown(":green[✅ Paid and confirmed by the seller. Enjoy!]")
                rate_the_seller(request_id, listings.plain_text(seller_name) if seller_name
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
