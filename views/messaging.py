"""Authenticated Messaging page registered in the main app navigation.

No standalone login or fake data. All operations go through the repository.
"""

from datetime import datetime
from uuid import uuid4

import streamlit as st

from accounts import logged_in_user, verified_nova_email
from messaging import MAX_MESSAGE_LENGTH
import messaging_repository as repository

email = verified_nova_email(logged_in_user())
if email is None or not st.user.is_logged_in:
    st.info("Please sign in with your verified @novasbe.pt account to open Messages.")
    st.stop()

# Drop navigation and pending text if the logged-in account changes.
if st.session_state.get("messaging_account") != email:
    for key in ("messaging_selected", "messaging_pending", "messaging_history_limit"):
        st.session_state.pop(key, None)
    st.session_state.messaging_account = email


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
    st.caption(f"€{row['listing_price_snapshot']}")


def show_time(value: str) -> None:
    st.caption(datetime.fromisoformat(value).strftime("%d %b %Y · %H:%M %Z"))


def try_send(pending: dict) -> None:
    try:
        with st.spinner("Sending message…"):
            repository.send_message(pending["conversation_id"], pending["body"], pending["id"])
    except Exception as error:
        report_error(error)
    else:
        st.session_state.pop("messaging_pending", None)
        st.rerun()


st.title("Messages")
st.caption("Keep your marketplace conversations together.")
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

selected = st.session_state.get("messaging_selected")
if selected is None:
    st.subheader("Inbox")
    st.button("Refresh inbox")
    try:
        with st.spinner("Loading conversations…"):
            rows = repository.get_inbox()
    except Exception as error:
        report_error(error)
        st.stop()
    if not rows:
        st.info("No conversations yet. Conversations will appear here when you contact a seller or a buyer contacts you.")
    for row in rows:
        with st.container(border=True):
            st.subheader(row["other_name"])
            show_listing(row)
            last = row["last_message"]
            if last:
                prefix = "You: " if last["sender_id"] == row["own_profile_id"] else ""
                st.text(prefix + last["body"][:120] + ("…" if len(last["body"]) > 120 else ""))
                show_time(last["created_at"])
            else:
                st.caption("No messages yet")
            if st.button("Open chat", key=f"chat_{row['id']}"):
                st.session_state.messaging_selected = row["id"]
                st.session_state.messaging_history_limit = 50
                st.rerun()
else:
    if st.button("← Back to Inbox"):
        st.session_state.pop("messaging_selected", None)
        st.rerun()
    st.button("Refresh chat")
    limit = st.session_state.get("messaging_history_limit", 50)
    try:
        with st.spinner("Loading chat…"):
            row = repository.get_conversation_details(selected)
            history = repository.get_messages(selected, limit=limit)
    except Exception as error:
        report_error(error)
        st.stop()
    st.subheader(row["other_name"])
    with st.container(border=True):
        show_listing(row)
    if not history:
        st.info("No messages yet. Send the first message below.")
    if len(history) == limit and limit < 100:
        if st.button("Show more history"):
            st.session_state.messaging_history_limit = 100
            st.rerun()
    elif len(history) == 100:
        st.caption("Showing the latest 100 messages.")
    for message in history:
        own = message["sender_id"] == row["own_profile_id"]
        with st.chat_message("user" if own else "assistant"):
            st.caption("You" if own else row["other_name"])
            st.text(message["body"])
            show_time(message["created_at"])
    pending = st.session_state.get("messaging_pending")
    if pending and pending["conversation_id"] == selected:
        st.warning("Your last send was not confirmed. Retry uses the same message ID to avoid duplicates.")
        st.text(pending["body"])
        if st.button("Retry message"):
            try_send(pending)
        if st.button("Dismiss pending message"):
            st.session_state.pop("messaging_pending", None)
            st.rerun()
    body = st.chat_input("Write a message…", max_chars=MAX_MESSAGE_LENGTH,
                         disabled=pending is not None, key=f"compose_{selected}")
    if pending and pending["conversation_id"] != selected:
        st.info("A message in another chat needs retrying or dismissing before you send another.")
    if body is not None:
        pending = {"conversation_id": selected, "body": body, "id": str(uuid4())}
        st.session_state.messaging_pending = pending
        try_send(pending)
