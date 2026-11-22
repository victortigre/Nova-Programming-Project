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
    assert not columns[-1].button
    header = next(c for c in toolbar.get('flex_container') if c.key == 'chat-participant-header')
    assert header.subheader[0].value == ROW['other_name']
    assert not header.caption
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
    # Every offer card: the offered price with the listing price crossed out.
    assert any('~~€20.00~~' in h.value for h in card.subheader)
    if status != 'accepted':  # the accepted card has one "Offer accepted" tag instead
        assert any(t.value == f'Status: {status.title()}' for t in card.text)
    if actor != sender:
        assert card.text[0].value == ROW['other_name']
    buy = [b for b in card.button if b.label == 'Buy Now']
    if status == 'accepted' and actor == 7:
        assert len(buy) == 1 and buy[0].key == 'buy_now_' + OID
        # The buyer can start the purchase (bank transfer, see deals.buy_now).
        assert not buy[0].disabled and buy[0].proto.type == 'primary'
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
    # An unread chat shows its name and a counter of new messages.
    assert '<strong>Test participant</strong>' in before
    assert 'inbox-summary inbox-unread' in before
    assert '<span class="inbox-count">1</span>' in before
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


@pytest.mark.parametrize('name,title', [
    ('Jonathan', 'Surfboard'),
    ('Jonathan with a longer participant name', 'A long listing title that wraps on a narrow screen'),
])
def test_header_text_resets_caption_compensation_for_compact_spacing(ui, name, title):
    app, mocks, _ = ui
    mocks['get_conversation_details'].return_value = {**ROW, 'other_name': name, 'listing_title_snapshot': title}
    app.run()
    app.button(key='chat_' + CID).click().run()
    assert not app.exception
    header = next(c for c in app.get('flex_container') if c.key == 'chat-participant-header')
    assert header.subheader[0].value == name
    assert not header.caption
    styles = html(app)
    assert ".st-key-chat-participant-header [data-testid='stCaptionContainer'] {color:#737985;margin:0;}" in styles
    assert ".st-key-chat-participant-header [data-testid='stCaptionContainer'] p {margin:0;line-height:1.4;}" in styles
    # The single name element stays centered alongside the photo.
    photo, details = header.get('column')
    assert not photo.subheader and details.subheader[0].value == name
    assert not details.caption
    toolbar = next(c for c in app.get('flex_container') if c.key == 'chat-toolbar')
    assert toolbar.get('column')[0].button[0].label == '← Back to Inbox'
    assert not toolbar.get('column')[-1].button


def test_name_only_header_is_centered_and_preserves_inbox_and_offer_details(ui):
    from streamlit.proto.Block_pb2 import Block
    app, mocks, _ = ui
    mocks['get_inbox'].return_value = [{**ROW, 'last_activity': OFFER, 'unread': True}]
    mocks['get_chat_events'].return_value = [OFFER]
    mocks['get_offers'].return_value = [OFFER]
    app.run()
    assert not app.exception
    before = html(app)
    assert ROW['listing_title_snapshot'] in before
    assert 'Offer: €15.00 · Pending' in before
    assert '<span class="inbox-count">1</span>' in before  # the unread counter
    # The existing Inbox omits asking prices; preserve that, along with offer prices.
    assert '€20.00' not in before
    app.button(key='chat_' + CID).click().run()
    assert not app.exception
    header = next(c for c in app.get('flex_container') if c.key == 'chat-participant-header')
    photo, details = header.get('column')
    assert photo.proto.vertical_alignment == details.proto.vertical_alignment == Block.Column.CENTER
    assert [h.value for h in header.subheader] == [ROW['other_name']]
    assert not header.caption
    assert 'data:image/svg+xml,' in html(app)
    assert any(h.value.startswith('€15.00') and '~~€20.00~~' in h.value for h in app.subheader)
    assert any(c.value == 'COUNTEROFFER' or c.value == 'PRICE OFFER' for c in app.caption)
    next(b for b in app.button if b.label == '← Back to Inbox').click().run()
    assert not app.exception
    assert html(app) == before
