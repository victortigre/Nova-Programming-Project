"""Authenticated Messaging page registered in the main app navigation.

No standalone login or fake data. All operations go through the repository.
"""

from datetime import datetime
from uuid import uuid4

import streamlit as st

from accounts import logged_in_user, verified_nova_email
from messaging import MAX_MESSAGE_LENGTH
from listings import format_price
import messaging_repository as repository
import offer_ui
from offers import OFFER_STATUS_LABELS

email = verified_nova_email(logged_in_user())
if email is None or not st.user.is_logged_in:
    st.info("Please sign in with your verified @novasbe.pt account to open Messages.")
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

offer_ui.retry_panel()

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
            last = row.get("last_activity", row["last_message"])
            if last:
                prefix = "You: " if last["sender_id"] == row["own_profile_id"] else ""
                if last.get("type") == "offer":
                    st.text(prefix + f"Offer: {format_price(last['amount_cents'])} · {OFFER_STATUS_LABELS[last['status']]}")
                else:
                    st.text(prefix + last["body"][:120] + ("…" if len(last["body"]) > 120 else ""))
                show_time(last.get("activity_at", last["created_at"]))
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
            history = repository.get_chat_events(selected, limit=limit)
            latest_offers = repository.get_offers(selected, limit=1)
    except Exception as error:
        report_error(error)
        st.stop()
    agreement = None
    try:
        agreement = repository.get_buy_now_agreement(selected)
    except Exception:
        st.caption("Agreement preview is temporarily unavailable. You can still message and view offers.")
    negotiation_available = row["listing_id"] is not None and row.get("listing_status") == "active"
    if not negotiation_available:
        reason = {"reserved": "This listing is reserved.", "sold": "This listing has been sold.",
                  "unknown": "Listing availability could not be verified. Refresh chat to try again."}.get(
            row.get("listing_status"), "Listing no longer available.")
        st.info(reason + " Negotiation is unavailable; you can still exchange messages and view offer history.")
    st.subheader(row["other_name"])
    with st.container(border=True):
        show_listing(row)
    if agreement:
        st.success(f"Price agreed: {format_price(agreement['amount_cents'])}. Buy Now will be available at this price when checkout is enabled.")
        st.button("Buy Now — checkout coming soon", disabled=True)
        st.caption("This agreement has not reserved the item. No payment has been made.")
    if not history:
        st.info("No messages yet. Send the first message below.")
    if len(history) == limit and limit < 100:
        if st.button("Show more history"):
            st.session_state.messaging_history_limit = 100
            st.rerun()
    elif len(history) == 100:
        st.caption("Showing the latest 100 chat events.")
    current = latest_offers[0] if latest_offers else None
    for message in history:
        own = message["sender_id"] == row["own_profile_id"]
        if message["type"] == "offer":
            with st.container(border=True):
                st.caption("PRICE OFFER" if not message.get("parent_offer_id") else "COUNTEROFFER")
                st.subheader(format_price(message["amount_cents"]))
                st.caption(f"Original listing price: {format_price(row['price_cents'])}")
                st.text(f"From: {'You' if own else row['other_name']}")
                st.text(f"Status: {OFFER_STATUS_LABELS[message['status']]}")
                show_time(message["created_at"])
                if message.get("note"):
                    st.text(message["note"])
                if (current and current["id"] == message["id"] and message["status"] == "pending"
                        and not own and negotiation_available):
                    offer_ui.response_buttons(selected, message)
        else:
            with st.chat_message("user" if own else "assistant"):
                st.caption("You" if own else row["other_name"])
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
            st.rerun()
    body = st.chat_input("Write a message…", max_chars=MAX_MESSAGE_LENGTH,
                         disabled=pending is not None, key=f"compose_{selected}")
    if pending and pending["conversation_id"] != selected:
        st.info("A message in another chat needs retrying or dismissing before you send another.")
    if body is not None:
        pending = {"conversation_id": selected, "body": body, "id": str(uuid4())}
        st.session_state.messaging_pending = pending
        try_send(pending)
