"""Authenticated Messaging page registered in the main app navigation.

No standalone login or fake data. All operations go through the repository.

Speed: the inbox and the open chat are each an @st.fragment. Clicking inside
one (sending, Refresh, Show more) reruns only that part, not the whole app.
Reads run inside repository.checked_once(), so a page load checks the
signed-in student and the chat once instead of once per question.
"""

import html
from datetime import datetime
from uuid import uuid4

import streamlit as st
from streamlit.errors import StreamlitAPIException

import database
import deals
import payment_ui
from accounts import logged_in_user, verified_nova_email
from messaging import MAX_MESSAGE_LENGTH
from listings import format_price
import messaging_repository as repository
import messaging_ui
import offer_ui
from offers import OFFER_STATUS_LABELS

email = verified_nova_email(logged_in_user())
if email is None or not st.user.is_logged_in:
    st.info("Please sign in with your verified @novasbe.pt account to open Inbox.")
    st.stop()

# Drop navigation and pending text if the logged-in account changes.
offer_ui.sync_account(email)


def report_error(error: Exception) -> None:
    # Never expose provider response bodies, credentials, or tracebacks in the UI.
    if isinstance(error, ValueError):
        st.warning(str(error))
    else:
        st.error("Messages could not be loaded or saved. Messaging may still need database setup, or the service may be temporarily unavailable. Please try again later or contact the project team.")


def show_listing(row: dict) -> None:
    st.text(row["listing_title_snapshot"])
    if row["listing_id"] is None:
        st.caption("Listing no longer available")
    st.caption(format_price(row["price_cents"]))


def show_time(value: str) -> None:
    st.caption(datetime.fromisoformat(value).strftime("%d %b %Y · %H:%M %Z"))


def rerun_this_part() -> None:
    """Rerun only the fragment we are in. Streamlit refuses that during a
    full-page run (the first load), so then the whole page runs again."""
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


def try_send(pending: dict) -> None:
    try:
        with st.spinner("Sending message…"):
            repository.send_message(pending["conversation_id"], pending["body"], pending["id"])
    except ValueError as error:
        # The message itself was refused (for example only spaces). Trying the
        # same text again cannot work, so it is not kept as "pending": the
        # student can simply type a new message.
        st.session_state.pop("messaging_pending", None)
        report_error(error)
    except Exception as error:
        report_error(error)
    else:
        st.session_state.pop("messaging_pending", None)
        rerun_this_part()


@st.fragment
def show_inbox() -> None:
    messaging_ui.apply_inbox_styles()
    # No refresh button: app.py's live_updates reruns the page by itself when
    # a new message or offer arrives.
    try:
        with st.spinner("Loading conversations…"), repository.checked_once():
            rows = repository.get_inbox(include_photos=True)
    except Exception as error:
        report_error(error)
        return
    if not rows:
        st.subheader("Your inbox is empty")
        st.info("Your conversations will appear here when you contact someone or receive a message or offer.")
    if rows:
        with st.container(key="inbox-list"):
            for index, row in enumerate(rows):
                with st.container(key=f"inbox-row-{row['id']}"):
                    left, right = st.columns([4, 1], gap="small", vertical_alignment="center")
                    last = row.get("last_activity") or row.get("last_message")
                    with left:
                        # The name is a clickable button (another way to open the
                        # chat, besides "Open chat"); the summary below drops its own
                        # name heading so the name isn't shown twice. Unread is shown
                        # by the count badge and highlight (no dot), like elsewhere.
                        if st.button(row['other_name'], type="tertiary",
                                     key=f"openname_{row['id']}"):
                            st.session_state.messaging_selected = row["id"]
                            st.session_state.messaging_history_limit = 50
                            st.rerun()
                        messaging_ui.inbox_summary(row, last, with_name=False)
                    with right:
                        with st.container(key=f"inbox-actions-{row['id']}", horizontal_alignment="right"):
                            with st.container(key=f"inbox-time-{row['id']}"):
                                # Unread: the time turns violet, with a counter under it.
                                with st.container(key=(f"inbox-unreadtime-{row['id']}"
                                                       if row.get("unread") else None)):
                                    st.caption(messaging_ui.inbox_timestamp(
                                        (last.get("activity_at") or last["created_at"])
                                        if last else row["created_at"]))
                                if row.get("unread"):
                                    count = row.get("unread_count") or 1
                                    st.html(f'<span class="inbox-count">{min(count, 99)}</span>')
                            with st.container(horizontal_alignment="right"):
                                if st.button("Open chat", key=f"chat_{row['id']}", type="secondary"):
                                    st.session_state.messaging_selected = row["id"]
                                    st.session_state.messaging_history_limit = 50
                                    st.rerun()  # Keep navigation as a whole-page rerun.
                if index < len(rows) - 1:
                    st.divider()


def offer_price(amount: int, original: int | None, own: bool) -> str:
    """'€80.00  ~~€82.50~~': the offered price, with the listing price crossed out.

    On your own (violet) bubbles the crossed-out price stays white, so it can
    be read; on the other person's (grey) bubbles it is grey.
    """
    if original is None or original == amount:
        return format_price(amount)
    crossed = f"~~{format_price(original)}~~"
    return f"{format_price(amount)}  " + (crossed if own else f":grey[{crossed}]")


def accepted_offer_card(message: dict, row: dict, current: dict | None, live_deal: bool,
                        negotiation_available: bool, selected: str) -> None:
    """An accepted offer: one "Offer accepted" tag, the price (the listing price
    crossed out), who accepted, and what happens next for this side."""
    amount, original = message["amount_cents"], row.get("price_cents")
    st.badge("Offer accepted", icon=":material/check:", color="green")
    own = message["sender_id"] == row["own_profile_id"]
    st.subheader(offer_price(amount, original, own))
    first = (row.get("other_name") or "They").split(" ")[0]
    i_proposed = message["sender_id"] == row["own_profile_id"]
    # In its own keyed box with some space on top: the chat styles pull the
    # line under a subheader up into it otherwise.
    with st.container(key=f"dm-accepted-by-{message['id']}"):
        if message.get("note"):
            st.text(message["note"])
        st.text(f"{first} accepted your offer." if i_proposed
                else f"You accepted {first}'s offer.")
    buyer_here = row["own_profile_id"] == row["buyer_id"]
    is_current = current is not None and current["id"] == message["id"]
    if is_current and live_deal:
        next_step(message, "The purchase has started", "See the payment below.")
        return
    if buyer_here:
        # Buy Now starts the purchase at this price (deals.buy_now checks
        # everything again) and shows where to pay below.
        can_buy = is_current and negotiation_available and not live_deal
        if st.button("Buy Now", key=f"buy_now_{message['id']}", type="primary",
                     disabled=not can_buy, width="stretch"):
            try:
                deals.buy_now(database, email, selected)
            except deals.ListingError as exc:
                st.error(" ".join(exc.errors))
            except (deals.NotAllowed, deals.NotFound) as exc:
                st.error(str(exc))
            except Exception:
                st.error("Buying isn't available right now. Please try again later.")
            else:
                st.session_state["payment_message"] = (
                    "Reserved for you! See below how to pay the seller.")
                st.rerun()
        if can_buy:
            st.caption("Reserves the item and shows where to pay. You have 15 minutes.")
    elif is_current and negotiation_available:
        next_step(message, f"Next: {first} pays you",
                  "They tap Buy Now, see how to pay you and have 15 minutes (or pay cash "
                  "when you meet).")


def next_step(message: dict, title: str, text: str) -> None:
    """A small grey box with a clock: what happens next. One html block, so the
    title and its line can't overlap. Names are escaped before they go in."""
    with st.container(key=f"next-step-{message['id']}"):
        st.html('<div class="nm-next-step"><span class="nm-next-icon">🕒</span><div>'
                f'<div class="nm-next-title">{html.escape(title)}</div>'
                f'<div class="nm-next-text">{html.escape(text)}</div></div></div>')


@st.fragment
def show_chat(selected: str) -> None:
    messaging_ui.apply_open_chat_styles()
    with st.container(key="open-chat-surface"):
        with st.container(key="chat-toolbar"):
            back, participant, refresh = st.columns([1.8, 6.4, 1.8], gap="small", vertical_alignment="center")
            with back:
                if st.button("← Back to Inbox"):
                    st.session_state.pop("messaging_selected", None)
                    st.rerun()  # The whole page: it switches back to the inbox.
            with participant:
                participant_header = st.empty()
            # Preserve the empty right column so the participant header stays aligned.
        with st.container(key="chat-header-divider"):
            st.divider()
        limit = st.session_state.get("messaging_history_limit", 50)
        try:
            with st.spinner("Loading chat…"), repository.checked_once():
                row = repository.get_conversation_details(selected)
                history = repository.get_chat_events(selected, limit=limit)
                latest_offers = repository.get_offers(selected, limit=1)
        except Exception as error:
            report_error(error)
            return
        # Opening the chat marks it read, so it drops off the Inbox unread badge.
        # Best-effort: a failure here must never stop the chat from showing.
        try:
            repository.mark_read(selected)
        except Exception:
            pass
        negotiation_available = row["listing_id"] is not None and row.get("listing_status") == "active"
        if not negotiation_available:
            reason = {"reserved": "This listing is reserved.", "sold": "This listing has been sold.",
                      "unknown": "Listing availability could not be verified. Refresh chat to try again."}.get(
                row.get("listing_status"), "Listing no longer available.")
            notice = reason + " Negotiation is unavailable; you can still exchange messages and view offer history."
            if row.get("listing_status") == "reserved":
                st.caption(notice)
            else:
                st.info(notice)
        with participant_header.container():
            messaging_ui.chat_header(row, divider=False)
        if not history:
            st.info("No messages yet. Send the first message below.")
        if len(history) == limit and limit < 100:
            if st.button("Show more history"):
                st.session_state.messaging_history_limit = 100
                rerun_this_part()
        elif len(history) == 100:
            st.caption("Showing the latest 100 chat events.")
        current = latest_offers[0] if latest_offers else None
        # A purchase started from this chat with Buy Now (deals.py), if any.
        try:
            deal = deals.deal_in_chat(database, email, selected)
        except Exception:  # buying isn't set up in the database yet
            deal = None
        live_deal = deal is not None and deal["status"] in (deals.ACCEPTED, deals.COMPLETED)
        payment_ui.show_message()
        for message, separator, show_avatar in messaging_ui.chat_event_groups(history):
            if separator:
                messaging_ui.date_separator(separator)
            with messaging_ui.message_bubble(message, row, compact=True,
                                             show_avatar=show_avatar) as own:
                if message["type"] == "offer" and message["status"] == "accepted":
                    accepted_offer_card(message, row, current, live_deal, negotiation_available,
                                        selected)
                elif message["type"] == "offer":
                    st.caption("PRICE OFFER" if not message.get("parent_offer_id") else "COUNTEROFFER")
                    st.subheader(offer_price(message["amount_cents"], row.get("price_cents"), own))
                    # Own keyed box with space on top: the chat styles pull the line
                    # under a subheader up into it otherwise.
                    with st.container(key=f"dm-offer-details-{message['id']}"):
                        status_text = OFFER_STATUS_LABELS[message["status"]]
                        # Nobody can answer it now: say why instead of "Pending".
                        if message["status"] == "pending" and not negotiation_available:
                            status_text = {
                                "reserved": "On hold: the item is reserved",
                                "sold": "Expired: the item is no longer on sale",
                                "unavailable": "Expired: the item is no longer on sale",
                            }.get(row.get("listing_status"), status_text)
                        st.text(f"Status: {status_text}")
                        if message.get("note"):
                            st.text(message["note"])
                    if (current and current["id"] == message["id"] and message["status"] == "pending"
                            and not own and negotiation_available):
                        offer_ui.response_buttons(selected, message)
                if message["type"] == "offer":
                    messaging_ui.chat_timestamp(message)
                else:
                    st.text(message["body"])
                    messaging_ui.chat_timestamp(message)
        # The payment of this chat's purchase: where to pay, and each side's buttons.
        if live_deal:
            with st.container(border=True, key=f"chat-payment-{deal['id']}"):
                st.markdown("**Payment**")
                if row["own_profile_id"] == row["buyer_id"]:
                    payment_ui.buyer_box(deal, email, where="chat")
                else:
                    payment_ui.seller_box(deal, email, where="chat",
                                          buyer_name=row["other_name"])
        # A free item has no price to negotiate, so no offer form for it.
        if (row["own_profile_id"] == row["buyer_id"] and negotiation_available
                and row["price_cents"] and (not current or current["status"] == "declined")):
            with st.expander("Make an Offer"):
                offer_ui.show_form(f"chat-{selected}", default_cents=row["price_cents"], conversation_id=selected)
        pending = st.session_state.get("messaging_pending")
        if pending and pending["conversation_id"] == selected:
            st.warning("Your last send was not confirmed. Retry uses the same message ID to avoid duplicates.")
            st.text(pending["body"])
            if st.button("Retry message"):
                try_send(pending)
            if st.button("Dismiss pending message"):
                st.session_state.pop("messaging_pending", None)
                rerun_this_part()
    body = st.chat_input("Write a message…", max_chars=MAX_MESSAGE_LENGTH,
                         disabled=pending is not None, key=f"compose_{selected}")
    if pending and pending["conversation_id"] != selected:
        st.info("A message in another chat needs retrying or dismissing before you send another.")
    if body is not None:
        pending = {"conversation_id": selected, "body": body, "id": str(uuid4())}
        st.session_state.messaging_pending = pending
        try_send(pending)


messaging_ui.apply_chat_styles()
if st.session_state.get("messaging_selected") is None:
    st.title("Inbox")
# One page load = one check of the signed-in student, shared by everything below.
with repository.checked_once():
    try:
        configured = repository.is_configured()
        if configured:
            repository.require_access()
    except Exception as error:
        report_error(error)
        st.stop()
    if not configured:
        st.info("Messaging is not set up yet. The project team needs to configure Supabase and prepare the Messaging tables. Your demo is still available separately.")
        st.stop()

    offer_ui.retry_panel()

    selected = st.session_state.get("messaging_selected")
    if selected is None:
        show_inbox()
    else:
        show_chat(selected)
