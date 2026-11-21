"""Independent UI demo. Run: streamlit run messaging_demo.py.

Intentionally separate from the authenticated marketplace and Supabase.
All identities and listings are fictional; messages last only this session.
"""

from datetime import datetime

import streamlit as st

from messaging_demo_data import (
    DEMO_USER_ID,
    MAX_MESSAGE_LENGTH,
    inbox,
    message_history,
    new_demo_store,
    send_message,
)

st.set_page_config(page_title="Messages · Nova Marketplace demo", page_icon="💬", layout="wide")


def timestamp(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%d %b · %H:%M UTC")


def show_inbox(store: dict) -> None:
    st.title("Your inbox")
    st.caption("A little less scrolling. A little more connecting.")
    conversations = inbox(store, DEMO_USER_ID)
    if not conversations:
        st.info("No conversations yet.")
    for row in conversations:
        listing = row["listing"]
        with st.container(border=True):
            thumbnail, preview, action = st.columns([1, 7, 2], vertical_alignment="center")
            thumbnail.subheader(listing["icon"])
            preview.subheader(row["other_name"])
            preview.write(f"{listing['title']} · €{listing['price']}")
            last = row["last_message"]
            if last:
                prefix = "You: " if last["sender_id"] == DEMO_USER_ID else ""
                preview.text(prefix + last["body"][:120] + ("…" if len(last["body"]) > 120 else ""))
                preview.caption(timestamp(last["created_at"]))
            else:
                preview.caption("Start the conversation")
            if action.button("Open chat", key=f"open_{row['id']}", use_container_width=True):
                st.session_state.messaging_demo_selected = row["id"]
                st.rerun()


def show_chat(store: dict, conversation_id: int) -> None:
    row = next((row for row in inbox(store, DEMO_USER_ID) if row["id"] == conversation_id), None)
    if row is None:
        st.session_state.messaging_demo_selected = None
        st.rerun()
    if st.button("← Back to inbox"):
        st.session_state.messaging_demo_selected = None
        st.rerun()
    st.title(row["other_name"])
    listing = row["listing"]
    with st.container(border=True):
        st.subheader(f"{listing['icon']} {listing['title']}")
        st.write(f"€{listing['price']} · Demo listing")
    for message in message_history(store, conversation_id, DEMO_USER_ID):
        own = message["sender_id"] == DEMO_USER_ID
        with st.chat_message("user" if own else "assistant", avatar="🙂" if own else "👤"):
            st.caption("You" if own else row["other_name"])
            st.text(message["body"])
            st.caption(timestamp(message["created_at"]))
    body = st.chat_input("Write a message…", max_chars=MAX_MESSAGE_LENGTH, key=f"message_{conversation_id}")
    if body is not None:
        try:
            send_message(store, conversation_id, DEMO_USER_ID, body)
        except ValueError as error:
            st.error(str(error))
        else:
            st.rerun()


if "messaging_demo_store" not in st.session_state:
    st.session_state.messaging_demo_store = new_demo_store()
    st.session_state.messaging_demo_selected = None

with st.sidebar:
    st.header("Nova Marketplace")
    st.caption("MESSAGING DEMO")
    st.write("Signed in as **You (demo)**")
    st.info("Fictional users and listings. No login or database connection.")
    st.caption("Messages survive navigation within this session. Reloading or opening a new session resets them. There are no automatic replies or live updates from other users.")
    if st.button("Reset demo"):
        st.session_state.messaging_demo_store = new_demo_store()
        st.session_state.messaging_demo_selected = None
        st.rerun()

st.caption("NOVA MARKETPLACE / MESSAGES")
selected = st.session_state.messaging_demo_selected
if selected is None:
    show_inbox(st.session_state.messaging_demo_store)
else:
    show_chat(st.session_state.messaging_demo_store, selected)
