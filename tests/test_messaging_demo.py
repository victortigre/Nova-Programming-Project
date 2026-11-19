"""Demo-store behavior independent of Streamlit and Supabase."""

import pytest

from messaging_demo_data import inbox, message_history, new_demo_store, send_message


def test_sending_updates_history_and_moves_conversation_to_top():
    store = new_demo_store()
    assert inbox(store, 1)[0]["id"] == 3
    send_message(store, 1, 1, "  Can I collect it today?  ")
    assert inbox(store, 1)[0]["id"] == 1
    assert message_history(store, 1, 1)[-1]["body"] == "Can I collect it today?"
    assert len(message_history(store, 2, 1)) == 2


@pytest.mark.parametrize("body", ["  ", "x" * 2001])
def test_invalid_messages_do_not_change_store(body):
    store = new_demo_store()
    with pytest.raises(ValueError):
        send_message(store, 1, 1, body)
    assert len(store["messages"]) == 6


def test_nonparticipant_cannot_read_or_send():
    store = new_demo_store()
    with pytest.raises(ValueError):
        message_history(store, 1, 3)
    with pytest.raises(ValueError):
        send_message(store, 1, 3, "Hello")


def test_new_sessions_have_independent_data():
    first, second = new_demo_store(), new_demo_store()
    send_message(first, 1, 1, "Hello")
    assert len(second["messages"]) == 6


def test_chat_navigation_sending_and_reset():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "messaging_demo.py")).run()
    assert not app.exception
    app.button(key="open_1").click().run()
    assert not app.exception
    app.chat_input[0].set_value("Demo message from the UI").run()
    assert not app.exception
    assert any(item.value == "Demo message from the UI" for item in app.text)
    next(button for button in app.button if button.label == "← Back to inbox").click().run()
    assert not app.exception
    assert inbox(app.session_state["messaging_demo_store"], 1)[0]["id"] == 1
    next(button for button in app.button if button.label == "Reset demo").click().run()
    assert not app.exception
    assert len(app.session_state["messaging_demo_store"]["messages"]) == 6
