"""Authenticated Messaging page registered in the main app navigation.

No standalone login or fake data. All operations go through the repository.

Speed: the inbox and the open chat are each an @st.fragment. Clicking inside
one (sending, Refresh, Show more) reruns only that part, not the whole app.
Reads run inside repository.checked_once(), so a page load checks the
signed-in student and the chat once instead of once per question.
"""

from datetime import datetime
from uuid import uuid4

import streamlit as st
from streamlit.errors import StreamlitAPIException

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
    except Exception as error:
        report_error(error)
    else:
        st.session_state.pop("messaging_pending", None)
        rerun_this_part()


@st.fragment
def show_inbox() -> None:
    messaging_ui.apply_inbox_styles()
    with st.container(key="inbox-toolbar", horizontal_alignment="right"):
        st.button("Refresh inbox")
    try:
        with st.spinner("Loading conversations…"), repository.checked_once():
            rows = repository.get_inbox()
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
                        messaging_ui.inbox_summary(row, last)
                    with right:
                        with st.container(key=f"inbox-time-{row['id']}"):
                            show_time((last.get("activity_at") or last["created_at"])
                                      if last else row["created_at"])
                        with st.container(horizontal_alignment="right"):
                            if st.button("Open chat", key=f"chat_{row['id']}", type="secondary"):
                                st.session_state.messaging_selected = row["id"]
                                st.session_state.messaging_history_limit = 50
                                st.rerun()  # Keep navigation as a whole-page rerun.
                if index < len(rows) - 1:
                    st.divider()


@st.fragment
def show_chat(selected: str) -> None:
    if st.button("← Back to Inbox"):
        st.session_state.pop("messaging_selected", None)
        st.rerun()  # The whole page: it switches back to the inbox.
    st.button("Refresh chat")
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
        st.info(reason + " Negotiation is unavailable; you can still exchange messages and view offer history.")
    st.subheader(row["other_name"])
    with st.container(border=True):
        show_listing(row)
    if not history:
        st.info("No messages yet. Send the first message below.")
    if len(history) == limit and limit < 100:
        if st.button("Show more history"):
            st.session_state.messaging_history_limit = 100
            rerun_this_part()
    elif len(history) == 100:
        st.caption("Showing the latest 100 chat events.")
    current = latest_offers[0] if latest_offers else None
    for message in history:
        with messaging_ui.message_bubble(message, row) as own:
            if message["type"] == "offer":
                st.caption("PRICE OFFER" if not message.get("parent_offer_id") else "COUNTEROFFER")
                accepted = message["status"] == "accepted"
                st.subheader(f"Offer Accepted — {format_price(message['amount_cents'])}" if accepted
                             else format_price(message["amount_cents"]))
                with st.container(key=f"dm-original-price-{message['id']}"):
                    st.caption(f"Original listing price: {format_price(row['price_cents'])}")
                st.text(f"Status: {OFFER_STATUS_LABELS[message['status']]}")
                show_time(message["created_at"])
                if message.get("note"):
                    st.text(message["note"])
                if accepted:
                    st.text(messaging_ui.accepted_offer_description(message, row))
                    if row["own_profile_id"] == row["buyer_id"]:
                        # Presentation only. No checkout callback or purchase write.
                        st.button("Buy Now", key=f"buy_now_{message['id']}",
                                  type="primary", disabled=True, width="stretch")
                    st.caption("Accepting this offer does not reserve or pay for the item.")
                if (current and current["id"] == message["id"] and message["status"] == "pending"
                        and not own and negotiation_available):
                    offer_ui.response_buttons(selected, message)
            else:
                st.text(message["body"])
                show_time(message["created_at"])
    if (row["own_profile_id"] == row["buyer_id"] and negotiation_available
            and (not current or current["status"] == "declined")):
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
