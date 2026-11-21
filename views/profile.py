"""My profile: a student fills in or changes their own profile, and sees the
listings they saved (tapped ♡ on)."""

from functools import partial

import streamlit as st

import browsing
import database
import listings
import reviews
import ui
import wallet
from accounts import logged_in_user, verified_nova_email
from profile_form import show_profile_form

# Who is using this page? The email always comes from the login, never from
# a form, so nobody can open or change someone else's profile here.
email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("My profile")

profile = database.get_profile(email)

if st.session_state.pop("profile_saved", False):
    st.success("Your profile is saved.")
elif profile is None:
    st.info("Welcome! Fill in your profile so other students know who they are dealing with.")

if profile is not None:
    st.page_link(
        "views/public_profile.py",
        label="See my profile as other students see it",
        query_params={"id": profile["id"]},
    )

with ui.card("profile-form"):
    show_profile_form(email, profile)

# --- Nova credits (wallet.py) ------------------------------------------------------
# Pretend money for this course project: add some with the buttons, spend it
# on items, receive it when you sell.


def add_credits(amount_cents: int) -> None:
    try:
        wallet.add_credits(database, email, amount_cents)
        st.session_state["wallet_message"] = f"Added {wallet.euros(amount_cents)} in credits."
    except (wallet.WalletError, wallet.NotAllowed) as exc:
        st.session_state["wallet_error"] = str(exc)


def add_typed_credits() -> None:
    """Read the euros typed in the box and add that amount (so a big top-up
    like €4,000 doesn't need many button clicks)."""
    try:
        cents = listings.parse_price(st.session_state.get("topup-amount", ""))
    except ValueError:
        st.session_state["wallet_error"] = "Enter an amount like 40 or 4000."
        return
    if not cents:
        st.session_state["wallet_error"] = "Enter an amount to add."
        return
    add_credits(cents)
    st.session_state["topup-amount"] = ""  # empty the box after a successful add


if profile is not None:
    with ui.card("wallet"):
        st.markdown("**Nova credits**")
        try:
            balance = wallet.my_balance(database, email)
            history = wallet.my_history(database, email)
        except Exception:  # the wallet table isn't in the database yet
            balance, history = None, []
        if balance is None:
            st.caption("Credits aren't set up in the database yet. Whoever manages the "
                       "database needs to run `database_setup.sql`.")
        else:
            st.html(f'<p class="nm-price">{wallet.euros(balance)}</p>')
            st.caption("Demo credits for this course project, not real money. When a seller "
                       "accepts your request, the price is held; it goes to the seller when "
                       "you confirm you got the item.")
            if message := st.session_state.pop("wallet_message", None):
                st.success(message)
            if error := st.session_state.pop("wallet_error", None):
                st.error(error)
            for column, amount in zip(st.columns(len(wallet.TOP_UP_AMOUNTS)),
                                      wallet.TOP_UP_AMOUNTS):
                column.button(f"+ {wallet.euros(amount)}", key=f"topup-{amount}",
                              on_click=add_credits, args=(amount,), width="stretch")
            st.caption("Or type any amount:")
            box, add = st.columns([3, 1], vertical_alignment="bottom")
            box.text_input("Amount (€)", key="topup-amount", placeholder="e.g. 4000",
                           label_visibility="collapsed")
            add.button("Add", key="topup-custom", on_click=add_typed_credits, width="stretch")
            if history:
                with st.expander("History"):
                    for entry in history[:30]:
                        amount = entry["amount_cents"]
                        sign = ":green[+" if amount > 0 else "−"
                        end = "]" if amount > 0 else ""
                        st.markdown(f"{sign}{wallet.euros(abs(amount))}{end} · "
                                    f"{listings.plain_text(entry['text'])}")

# --- My ratings (reviews.py) ----------------------------------------------------
# What other students said about you after finished deals. You rate others
# from "My purchases" and "My listings".
if profile is not None:
    try:
        rating = reviews.summary(database, profile["id"])
        feedback = reviews.recent_feedback(database, profile["id"], limit=10)
    except Exception:  # the reviews table isn't in the database yet
        rating = None
    if rating is not None:
        with ui.card("ratings"):
            st.markdown("**My ratings**")
            if rating["count"]:
                plural = "s" if rating["count"] != 1 else ""
                st.markdown(f"**★ {rating['average']:.1f}** ({rating['count']} rating{plural}) "
                            f"· {rating['sold']} sold through the app")
            else:
                st.caption("No ratings yet. After a finished deal, the other student can "
                           "rate you here.")
            for item in feedback:
                st.markdown(f"{reviews.star_text(item['stars'])} · "
                            f"**{listings.plain_text(item['reviewer_name'])}**")
                st.caption(listings.plain_text(item["comment"]))

# --- Saved items ---------------------------------------------------------------
# The listings this student liked. Tapping ♥ removes one; tapping the price
# opens it on Browse, the same way a student's public profile does.
SAVED_COLUMNS = 3


def unsave(listing_id: int) -> None:
    browsing.toggle_saved(database, profile["id"], listing_id)


if profile is not None:
    with ui.card("saved-items"):
        try:
            saved_items = browsing.saved_listings(database, profile["id"])
        except Exception:
            saved_items = None
        st.html(f'<p style="font-weight: 600; margin: 0;">{ui.heart_icon(18)} '
                f"Saved items ({len(saved_items or [])})</p>")
        if saved_items is None:
            st.caption("Saving isn't set up in the database yet. Whoever manages the "
                       "database needs to run `database_setup.sql`.")
        elif not saved_items:
            ui.hint_with_heart("You haven't saved anything yet. "
                               "Tap {heart} on a listing to keep it here.")
            st.page_link("views/browse.py", label="Browse items", icon=":material/search:")
        else:
            # One request for all cover photo links, instead of one per card.
            links = database.listing_photo_urls(
                [item["photo_paths"][0] for item in saved_items if item["photo_paths"]])
            for start in range(0, len(saved_items), SAVED_COLUMNS):
                row = st.columns(SAVED_COLUMNS, gap="medium")
                for column, item in zip(row, saved_items[start:start + SAVED_COLUMNS]):
                    cover = item["photo_paths"][0] if item["photo_paths"] else None
                    with column:
                        clicked = ui.listing_card(
                            item, links.get(cover), key=f"saved-{item['id']}",
                            saved=True, on_heart=partial(unsave, item["id"]))
                    if clicked:
                        st.session_state["open_listing"] = item["id"]
                        st.switch_page("views/browse.py")

# The menu bar has no room for the account, so signing out is here.
with ui.card("account"):
    st.markdown("**Account**")
    st.caption(f"Signed in as {email}")
    st.page_link("views/house_rules.py", label="House rules", icon=":material/gavel:")
    st.button("Sign out", icon=":material/logout:", on_click=st.logout)
