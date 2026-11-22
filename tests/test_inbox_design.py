"""Authenticated production-page presentation with mocked transport, no services."""
from messaging_ui import lisbon_datetime
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1.errors import AppTestError

import database
import messaging_repository as repository
from test_messaging_ui import ui, ROW, CID
from test_offer_ui import OFFER, OID

REAL_INBOX = repository.get_inbox
REAL_DETAILS = repository.get_conversation_details
SECOND = '33333333-3333-4333-8333-333333333333'


def open_chat(ui):
    app, mocks, _ = ui
    app.run()
    app.button(key='chat_' + CID).click().run()
    assert not app.exception
    return app, mocks


def html_content(app):
    return '\n'.join(element.proto.body for element in app.get('html'))


def test_inbox_heading_has_no_subtitle_or_duplicate_heading(ui):
    app, mocks, _ = ui
    app.run()
    assert not app.exception
    assert [item.value for item in app.title] == ['Inbox']
    assert not any(item.value == 'Inbox' for item in app.subheader)
    assert not any('Keep your marketplace' in item.value for item in app.caption)
    assert not any(item.value == 'Your inbox is empty' for item in app.subheader)
    mocks['get_inbox'].return_value = []
    app.run()
    assert any(item.value == 'Your inbox is empty' for item in app.subheader)
    assert app.info[0].value == 'Your conversations will appear here when you contact someone or receive a message or offer.'
    assert not any(button.label == 'Open chat' for button in app.button)
    assert not app.selectbox


def test_unified_inbox_uses_one_real_actor_for_buying_and_selling(ui, monkeypatch):
    app, mocks, _ = ui
    buying = {**ROW, 'other_name': 'Seller'}
    selling = {**ROW, 'id': SECOND, 'buyer_id': 9, 'seller_id': 7, 'listing_id': 11,
               'listing_title_snapshot': 'My listing', 'other_name': 'Buyer'}
    rows = {CID: buying, SECOND: selling}
    query = MagicMock(return_value=[
        {'conversation': row, 'other_name': row['other_name'], 'last_message': None,
         'last_offer': None, 'newest_offer': None} for row in rows.values()])
    monkeypatch.setattr(repository, 'get_inbox', REAL_INBOX)
    monkeypatch.setattr(repository, 'get_conversation_details', REAL_DETAILS)
    monkeypatch.setattr(database, 'messaging_actor_profile', lambda email: {'id': 7, 'rules_accepted_at': 'accepted'})
    monkeypatch.setattr(database, 'messaging_inbox', query)
    monkeypatch.setattr(database, 'messaging_unread_conversations', lambda actor: [])
    monkeypatch.setattr(database, 'messaging_conversation', lambda cid, actor: rows.get(cid))
    monkeypatch.setattr(database, 'get_profile_by_id', lambda pid: {'name': {8: 'Seller', 9: 'Buyer'}[pid]})
    monkeypatch.setattr(database, 'get_listing', lambda lid: {'status': 'active'})
    monkeypatch.setattr(database, 'messaging_messages', lambda *args: [])
    monkeypatch.setattr(database, 'messaging_offers', lambda *args: [])
    app.run()
    assert not app.exception
    assert len([b for b in app.button if b.label == 'Open chat']) == 2
    assert '<strong>Buyer</strong>' in html_content(app)
    assert '<strong>Seller</strong>' in html_content(app)
    query.assert_called_with(7)
    for cid, other, can_start_offer in [(CID, 'Seller', True), (SECOND, 'Buyer', False)]:
        app.button(key='chat_' + cid).click().run()
        assert not app.exception
        assert app.subheader[0].value == other
        assert app.chat_input
        assert any(b.label == 'Send Offer' for b in app.button) == can_start_offer
        assert not app.selectbox
        next(b for b in app.button if b.label == '← Back to Inbox').click().run()
    database._client.assert_not_called()


@pytest.mark.parametrize('actor', [7, 8])
@pytest.mark.parametrize('photo', [None, 'https://photos.example.invalid/profile.jpg'])
def test_bubbles_follow_authenticated_actor_and_preserve_history(ui, actor, photo):
    app, mocks, _ = ui
    other = 'Seller Alex' if actor == 7 else 'Buyer Sam'
    mocks['get_conversation_details'].return_value = {**ROW, 'own_profile_id': actor,
                                                    'other_name': other, 'other_photo_url': photo}
    history = [
        {'type': 'message', 'id': 1, 'sender_id': 7, 'body': 'First message', 'created_at': '2026-11-20T10:00:00+00:00'},
        {**OFFER, 'id': SECOND, 'sender_id': 7, 'status': 'superseded', 'note': 'Original offer note', 'created_at': '2026-11-20T10:01:00+00:00'},
        {'type': 'message', 'id': 2, 'sender_id': 8, 'body': 'Second message', 'created_at': '2026-11-20T10:02:00+00:00'},
        {**OFFER, 'sender_id': 8, 'parent_offer_id': SECOND, 'note': 'Counteroffer note', 'created_at': '2026-11-20T10:03:00+00:00'},
    ]
    mocks['get_chat_events'].return_value = history
    mocks['get_offers'].return_value = [history[-1]]
    app, _ = open_chat(ui)
    containers = app.get('flex_container')
    keys = [c.key for c in containers if c.key and c.key.startswith('dm-event-')]
    assert keys == [f"dm-event-{'own' if item['sender_id'] == actor else 'other'}-{item['type']}-{item['id']}" for item in history]
    assert sum(c.key and c.key.startswith('dm-sender-name-') or False for c in containers) == 2
    assert sum(t.value == other for t in app.text) == 2
    assert not any(t.value.startswith('From:') or t.value == 'You' for t in app.text)
    assert not any(c.value == 'You' for c in app.caption)
    for body in ('First message', 'Second message', 'Original offer note', 'Counteroffer note'):
        assert sum(t.value == body for t in app.text) == 1
    for event in history:
        timestamp = lisbon_datetime(event['created_at']).strftime('%H:%M')
        assert any(c.value == timestamp for c in app.caption)
    markup = html_content(app)
    assert 'data:image/svg+xml,' in markup  # fallback exists with or without photo
    if photo:
        assert photo in markup
    responses = [b.label for b in app.button if b.label in ('Accept', 'Decline', 'Counteroffer')]
    assert responses == (['Accept', 'Decline', 'Counteroffer'] if actor == 7 else [])
    assert app.chat_input and not app.chat_input[0].disabled
    assert not app.selectbox


@pytest.mark.parametrize('actor', [7, 8])
@pytest.mark.parametrize('sender', [7, 8])
def test_accepted_card_is_role_aware_and_only_the_buyer_gets_buy_now(ui, monkeypatch, actor, sender):
    app, mocks, _ = ui
    mocks['get_conversation_details'].return_value = {**ROW, 'own_profile_id': actor}
    accepted = {**OFFER, 'status': 'accepted', 'sender_id': sender}
    previous = {**OFFER, 'id': SECOND, 'status': 'superseded', 'sender_id': 15 - sender}
    mocks['get_chat_events'].return_value = [previous, accepted]
    mocks['get_offers'].return_value = [accepted]
    writes = []
    for name in ('insert_request', 'update_request', 'update_listing'):
        mock = MagicMock(side_effect=AssertionError('Showing the chat must not create purchases'))
        monkeypatch.setattr(database, name, mock)
        writes.append(mock)
    app, _ = open_chat(ui)
    # One "Offer accepted" tag; the price with the listing price crossed out.
    assert any(h.value.startswith('€15.00') and '~~€20.00~~' in h.value for h in app.subheader)
    assert any(t.value == 'Status: Superseded' for t in app.text)
    assert not any(t.value == 'Status: Accepted' for t in app.text)
    first = ROW['other_name'].split(' ')[0]
    expected = (f'{first} accepted your offer.' if actor == sender
                else f"You accepted {first}'s offer.")
    assert any(t.value == expected for t in app.text)
    if actor == 7:
        assert any(c.value.startswith('Reserves the item and shows where to pay') for c in app.caption)
    else:
        assert any('pays you' in e.proto.body for e in app.get('html'))
    assert not any(b.label in ('Accept', 'Decline', 'Counteroffer', 'Send Offer') for b in app.button)
    buy = [b for b in app.button if b.label == 'Buy Now']
    if actor == 7:
        # The buyer can start the purchase; nothing is written until they tap it.
        assert len(buy) == 1 and not buy[0].disabled and buy[0].proto.type == 'primary'
    else:
        assert not buy
    app.chat_input[0].set_value('Message after acceptance').run()
    assert not app.exception
    assert mocks['send_message'].call_args.args[:2] == (CID, 'Message after acceptance')
    mocks['get_buy_now_agreement'].assert_not_called()
    for write in writes:
        write.assert_not_called()


@pytest.mark.parametrize('status', ['reserved', 'sold', 'unavailable'])
def test_historical_acceptance_never_claims_item_is_unreserved(ui, status):
    app, mocks, _ = ui
    mocks['get_conversation_details'].return_value = {**ROW, 'listing_status': status}
    accepted = {**OFFER, 'status': 'accepted', 'sender_id': 7}
    mocks['get_chat_events'].return_value = [accepted]
    mocks['get_offers'].return_value = [accepted]
    app, _ = open_chat(ui)
    assert any(h.value.startswith('€15.00') for h in app.subheader)
    assert next(b for b in app.button if b.label == 'Buy Now').disabled
    assert any('Negotiation is unavailable' in item.value for item in list(app.info) + list(app.caption))
    assert not any('has not been reserved' in item.value for item in app.caption)
    assert app.chat_input


def test_profile_photo_failure_does_not_block_real_chat_details_or_sending(ui, monkeypatch):
    app, mocks, _ = ui
    monkeypatch.setattr(repository, 'get_conversation_details', REAL_DETAILS)
    monkeypatch.setattr(database, 'messaging_actor_profile', lambda email: {'id': 7, 'rules_accepted_at': 'accepted'})
    monkeypatch.setattr(database, 'messaging_conversation', lambda *args: dict(ROW))
    monkeypatch.setattr(database, 'get_profile_by_id', lambda pid: {'id': pid, 'name': 'Actual participant', 'photo_path': 'profile.jpg'})
    monkeypatch.setattr(database, 'get_listing', lambda lid: {'status': 'active'})
    photo = MagicMock(side_effect=RuntimeError('private signing response'))
    monkeypatch.setattr(database, 'photo_url', photo)
    mocks['get_chat_events'].return_value = [OFFER]
    mocks['get_offers'].return_value = [OFFER]
    app, _ = open_chat(ui)
    assert app.subheader[0].value == 'Actual participant'
    assert any(t.value == 'Actual participant' for t in app.text)
    assert 'data:image/svg+xml,' in html_content(app)
    assert 'private signing response' not in html_content(app)
    app.chat_input[0].set_value('Photo failure does not block chat').run()
    assert not app.exception
    assert mocks['send_message'].call_args.args[1] == 'Photo failure does not block chat'
    photo.assert_called_with('profile.jpg')
