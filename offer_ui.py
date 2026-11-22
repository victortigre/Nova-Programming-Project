"""Shared Streamlit offer forms/actions. Storage and authorization stay in the repository."""

from uuid import uuid4

import streamlit as st
from postgrest.exceptions import APIError

from listings import parse_price, price_text
from offers import validate_offer_note, validate_offer_price
import messaging_repository as repository


def sync_account(email: str) -> None:
    if st.session_state.get("messaging_account") != email:
        for key in list(st.session_state):
            if key.startswith("messaging_offer_") or key in (
                "messaging_selected", "messaging_pending", "messaging_history_limit",
            ):
                st.session_state.pop(key, None)
        st.session_state.messaging_account = email


def _execute(pending: dict) -> None:
    try:
        with st.spinner("Saving offer…"):
            conversation_id = pending.get("conversation_id")
            if conversation_id is None:
                conversation_id = repository.get_or_create_conversation(pending["listing_id"])["id"]
                # A send may commit and then time out. Remember this conversation
                # so retries can recover that action even if the listing is later
                # deleted; the database operation ID remains unchanged.
                pending["conversation_id"] = conversation_id
                st.session_state.messaging_offer_pending = pending
            if pending["action"] == "send":
                repository.send_offer(conversation_id, pending["amount_cents"], pending["operation_id"], pending["note"])
            elif pending["action"] == "counter":
                repository.counter_offer(conversation_id, pending["offer_id"], pending["amount_cents"], pending["operation_id"], pending["note"])
            else:
                action = repository.accept_offer if pending["action"] == "accept" else repository.decline_offer
                action(conversation_id, pending["offer_id"], pending["operation_id"])
    except ValueError as error:
        st.session_state.pop("messaging_offer_pending", None)
        st.warning(str(error))
        return
    except APIError as error:
        if error.code == "23514":
            st.session_state.pop("messaging_offer_pending", None)
            if pending["action"] == "send":
                st.warning("This offer could not be sent. You may already have an offer on this "
                           "item (see the chat in your Inbox), or the item is no longer on sale.")
            else:
                st.warning("This offer changed or the listing is no longer eligible. Refresh the chat before trying again.")
        else:
            st.error("The offer was not confirmed. Messaging may need database setup. Retry the same action below.")
        return
    except Exception:
        st.error("The offer was not confirmed. Please retry the same action below.")
        return
    st.session_state.pop("messaging_offer_pending", None)
    st.session_state.pop("messaging_offer_counter", None)
    st.session_state.pop("messaging_offer_browse", None)
    if pending.get("listing_id") is not None:
        st.session_state.messaging_selected = conversation_id
        st.session_state.messaging_history_limit = 50
        st.switch_page("views/messaging.py")
    st.rerun()


def retry_panel() -> None:
    pending = st.session_state.get("messaging_offer_pending")
    if pending:
        st.warning("An offer action is awaiting confirmation. Retry keeps its original operation ID to avoid duplicates.")
        if pending.get("amount_cents"):
            from listings import format_price
            st.text(format_price(pending["amount_cents"]))
        if pending.get("note"):
            st.text(pending["note"])
        if st.button("Retry offer action", key="messaging_offer_retry"):
            _execute(pending)
        if st.button("Dismiss offer action", key="messaging_offer_dismiss"):
            st.session_state.pop("messaging_offer_pending", None)
            st.rerun()
        st.caption("Dismiss does not undo an action that may already have succeeded. Refresh before sending another offer.")


def show_form(key: str, *, default_cents: int, conversation_id: str | None = None,
              listing_id: int | None = None, parent_id: str | None = None) -> None:
    with st.form(f"messaging_offer_form_{key}"):
        price = st.text_input("Proposed price (€)", value=price_text(default_cents), key=f"messaging_offer_price_{key}")
        note = st.text_area("Personal message (optional)", max_chars=2000, key=f"messaging_offer_note_{key}")
        submitted = st.form_submit_button("Send Counteroffer" if parent_id else "Send Offer",
                                         disabled=bool(st.session_state.get("messaging_offer_pending")))
    if submitted:
        try:
            amount = validate_offer_price(parse_price(price))
            note = validate_offer_note(note)
        except ValueError as error:
            st.warning(str(error))
            return
        pending = {"action": "counter" if parent_id else "send", "conversation_id": conversation_id,
                   "listing_id": listing_id, "offer_id": parent_id, "amount_cents": amount,
                   "note": note, "operation_id": str(uuid4())}
        st.session_state.messaging_offer_pending = pending
        _execute(pending)


def response_buttons(conversation_id: str, offer: dict) -> None:
    disabled = bool(st.session_state.get("messaging_offer_pending"))
    accept, decline, counter = st.columns(3)
    for column, action, label in ((accept, "accept", "Accept"), (decline, "decline", "Decline")):
        if column.button(label, key=f"messaging_offer_{action}_{offer['id']}", disabled=disabled):
            pending = {"action": action, "conversation_id": conversation_id,
                       "offer_id": offer["id"], "operation_id": str(uuid4())}
            st.session_state.messaging_offer_pending = pending
            _execute(pending)
    if counter.button("Counteroffer", key=f"messaging_offer_counter_{offer['id']}", disabled=disabled):
        st.session_state.messaging_offer_counter = offer["id"]
    if st.session_state.get("messaging_offer_counter") == offer["id"]:
        show_form(f"counter-{offer['id']}", default_cents=offer["amount_cents"],
                  conversation_id=conversation_id, parent_id=offer["id"])
