"""Open-chat-only presentation regression tests; no credentials or network."""
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1.errors import AppTestError

import messaging_repository as repository
import messaging_ui
from test_messaging_ui import ui, ROW, CID
from test_offer_ui import OFFER, OID
from test_messaging_navigation import navigation


def html(app):
    return '\n'.join(e.proto.body for e in app.get('html'))


def open_chat(ui, history=(), actor=7, photo=None):
    app, mocks, _ = ui
    mocks['get_conversation_details'].return_value = {**ROW, 'own_profile_id': actor, 'other_photo_url': photo}
    mocks['get_chat_events'].return_value = list(history)
    mocks['get_offers'].return_value = [e for e in history if e['type'] == 'offer'][-1:]
    app.run()
    app.button(key='chat_' + CID).click().run()
    assert not app.exception
    return app, mocks


@pytest.mark.parametrize('photo', [None, 'https://photos.example.invalid/profile.jpg'])
def test_compact_header_shares_toolbar_with_controls_and_white_surface(ui, photo):
    app, mocks = open_chat(ui, photo=photo)
    assert not app.title  # No oversized Inbox title in an individual chat.
    surface = next(c for c in app.get('flex_container') if c.key == 'open-chat-surface')
    toolbar = next(c for c in surface.get('flex_container') if c.key == 'chat-toolbar')
    columns = toolbar.get('column')
    assert columns[0].button[0].label == '← Back to Inbox'
    assert columns[-1].button[0].label == 'Refresh chat'
    header = next(c for c in toolbar.get('flex_container') if c.key == 'chat-participant-header')
    assert header.subheader[0].value == ROW['other_name']
    assert [c.value for c in header.caption] == [ROW['listing_title_snapshot'], '€20.00']
    assert 'data:image/svg+xml,' in html(app)
    if photo:
        assert photo in html(app)
    divider = next(c for c in surface.get('flex_container') if c.key == 'chat-header-divider')
    assert len(divider.get('divider')) == 1
    assert '.st-key-open-chat-surface' in html(app) and 'background: #FFFFFF' in html(app)
    assert 'font-size: 1rem' in html(app)
    # Composer stays outside the new surface, preserving its pinned placement.
    assert not surface.chat_input
    assert app.chat_input[0].key == 'compose_' + CID
    mocks['mark_read'].assert_called_once_with(CID)


@pytest.mark.parametrize('actor', [7, 8])
@pytest.mark.parametrize('sender', [7, 8])
@pytest.mark.parametrize('status', ['pending', 'accepted', 'declined', 'superseded'])
def test_every_offer_and_counteroffer_has_one_bottom_timestamp(ui, actor, sender, status):
    offer = {**OFFER, 'sender_id': sender, 'status': status,
             'parent_offer_id': CID, 'created_at': '2026-07-05T23:30:00Z'}
    app, _ = open_chat(ui, [offer], actor)
    side = 'own' if actor == sender else 'other'
    card = next(c for c in app.get('flex_container') if c.key == f'dm-{side}-offer-{OID}')
    # Last child follows all explanation, response buttons and Buy Now content.
    final = list(card.children.values())[-1]
    assert final.key == 'chat-time-offer-' + OID
    assert [c.value for c in final.caption] == ['00:30']
    assert sum(c.value == '00:30' for c in card.caption) == 1
    assert any(t.value == f'Status: {status.title()}' for t in card.text)
    assert any(c.value == 'Original listing price: €20.00' for c in card.caption)
    if actor != sender:
        assert card.text[0].value == ROW['other_name']
    buy = [b for b in card.button if b.label == 'Buy Now']
    if status == 'accepted' and actor == 7:
        assert len(buy) == 1 and buy[0].key == 'buy_now_' + OID
        assert buy[0].disabled and buy[0].proto.type == 'primary'
        with pytest.raises(AppTestError, match='disabled button'):
            buy[0].click()
    else:
        assert not buy
    responses = [b.label for b in card.button if b.label in ('Accept', 'Decline', 'Counteroffer')]
    assert responses == (['Accept', 'Decline', 'Counteroffer'] if status == 'pending' and actor != sender else [])


@pytest.mark.parametrize('sender', [7, 8])
def test_text_message_timestamp_is_inside_bubble_at_bottom(ui, sender):
    event = {'type': 'message', 'id': 1, 'sender_id': sender, 'body': 'Unchanged message',
             'created_at': '2026-03-29T01:30:00Z'}
    app, _ = open_chat(ui, [event])
    side = 'own' if sender == 7 else 'other'
    bubble = next(c for c in app.get('flex_container') if c.key == f'dm-{side}-message-1')
    final = list(bubble.children.values())[-1]
    assert final.key == 'chat-time-message-1'
    assert final.caption[0].value == '02:30'
    assert any(t.value == 'Unchanged message' for t in bubble.text)


def test_inbox_before_and_after_chat_keeps_list_and_unread_state(ui):
    app, mocks, _ = ui
    mocks['get_inbox'].return_value = [{**ROW, 'unread': True}]
    app.session_state['attention_signature'] = (3, 1, ())
    app.run()
    before = html(app)
    assert '.st-key-open-chat-surface' not in before
    assert app.title[0].value == 'Inbox'
    assert '<strong>🔵 Test participant</strong>' in before
    mocks['mark_read'].assert_not_called()
    app.button(key='chat_' + CID).click().run()
    assert not app.exception
    assert app.session_state['attention_signature'] == (3, 1, ())
    next(b for b in app.button if b.label == '← Back to Inbox').click().run()
    assert not app.exception
    assert html(app) == before
    assert app.title[0].value == 'Inbox'
    assert app.session_state['attention_signature'] == (3, 1, ())


def test_existing_navigation_unread_counter_is_preserved(navigation, monkeypatch):
    app, _, _, pages, _, _ = navigation
    unread = MagicMock(return_value={CID, OID})
    monkeypatch.setattr(repository, 'unread_conversations', unread)
    monkeypatch.setattr(repository, 'offers_to_answer', lambda: [])
    app.run()
    assert not app.exception
    inbox = next(p for p in pages if p.path == 'views/messaging.py')
    assert inbox.title == 'Inbox (2)'
    assert app.session_state['attention_signature'][0] == 2
    assert unread.called


def test_new_css_is_open_chat_scoped_and_does_not_restyle_buttons_or_inbox():
    css = messaging_ui.OPEN_CHAT_CSS
    assert 'width: 62%' in css and 'font-size: 0.88rem' in css
    assert 'border-color: #E5E7EB' in css and '@media (max-width: 700px)' in css
    assert 'button' not in css and 'inbox' not in css and 'stAppViewContainer' not in css
