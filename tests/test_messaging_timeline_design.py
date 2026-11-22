"""Stage 2 visual structure and unchanged interactive contract, without services."""
from datetime import datetime

import pytest
from streamlit.testing.v1.errors import AppTestError

import messaging_ui
from test_messaging_ui import ui, ROW, CID
from test_offer_ui import OFFER, OID


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def message(mid, sender, time):
    return {'id': mid, 'type': 'message', 'sender_id': sender,
            'body': f'Message {mid}', 'created_at': time}


def open_chat(ui, history, actor=7):
    app, mocks, _ = ui
    mocks['get_conversation_details'].return_value = {**ROW, 'own_profile_id': actor}
    mocks['get_chat_events'].return_value = history
    mocks['get_offers'].return_value = [e for e in history if e['type'] == 'offer'][-1:]
    app.run()
    app.button(key='chat_' + CID).click().run()
    assert not app.exception
    return app, mocks


def html(app):
    return '\n'.join(e.proto.body for e in app.get('html'))


@pytest.mark.parametrize('stamp,now,label', [
    ('2026-07-05T23:30:00Z', '2026-07-06T01:00:00+01:00', 'Today'),
    ('2026-07-05T22:59:00Z', '2026-07-06T01:00:00+01:00', 'Yesterday'),
    ('2026-03-29T01:30:00Z', '2026-03-29T23:30:00Z', 'Yesterday'),
    ('2026-10-24T23:30:00Z', '2026-10-26T00:00:00Z', 'Yesterday'),
    ('2026-11-19T12:00:00Z', '2026-11-21T12:00:00Z', '19 November 2026'),
])
def test_date_separator_labels_use_lisbon_calendar(stamp, now, label):
    assert messaging_ui.chat_date_label(stamp, now=instant(now)) == label


@pytest.mark.parametrize('times,labels,avatars', [
    (['2026-07-05T22:59:00Z', '2026-07-05T23:00:00Z'], ['Yesterday', 'Today'], [True, True]),
    (['2026-03-29T00:59:00Z', '2026-03-29T01:00:00Z'], ['Today', None], [True, False]),
    (['2026-10-25T00:30:00Z', '2026-10-25T01:30:00Z'], ['Today', None], [True, False]),
])
def test_avatar_grouping_handles_midnight_and_dst(times, labels, avatars):
    events = [message(i, 8, t) for i, t in enumerate(times)]
    now = instant(times[-1])
    result = list(messaging_ui.chat_event_groups(events, now=now))
    assert [r[0] for r in result] == events
    assert [r[1] for r in result] == labels
    assert [r[2] for r in result] == avatars


def test_grouping_preserves_input_window_and_mixed_events():
    events = [message(1, 8, '2026-11-19T10:00:00Z'),
              {**OFFER, 'sender_id': 8, 'created_at': '2026-11-19T10:01:00Z'},
              message(2, 7, '2026-11-19T10:02:00Z'),
              message(3, 8, '2026-11-19T10:03:00Z')]
    result = list(messaging_ui.chat_event_groups(events, now=instant('2026-11-21T12:00:00Z')))
    assert [r[0] for r in result] == events
    assert [r[2] for r in result] == [True, False, True, True]
    assert len(list(messaging_ui.chat_event_groups(events[:1]))) == 1


@pytest.mark.parametrize('actor', [7, 8])
def test_compact_bubbles_group_avatars_keep_sender_and_timestamp_at_bottom(ui, actor):
    events = [message(1, 8, '2026-07-05T22:59:00Z'),
              message(2, 8, '2026-07-05T23:00:00Z'),
              message(3, 8, '2026-07-05T23:01:00Z'),
              {**OFFER, 'sender_id': 7, 'created_at': '2026-07-05T23:02:00Z'}]
    app, mocks = open_chat(ui, events, actor)
    keys = [c.key for c in app.get('flex_container') if c.key]
    for event in events:
        side = 'own' if event['sender_id'] == actor else 'other'
        assert f'dm-event-{side}-{event["type"]}-{event["id"]}' in keys
        bubble = next(c for c in app.get('flex_container') if c.key == f'dm-{side}-{event["type"]}-{event["id"]}')
        time = bubble.get('flex_container')[-1]
        assert time.key == f'chat-time-{event["type"]}-{event["id"]}'
        assert time.caption[0].value == messaging_ui.lisbon_datetime(event['created_at']).strftime('%H:%M')
    assert 'chat-date-separator' in html(app)
    if actor == 7:
        assert '.st-key-dm-event-other-message-3::before { content: none; }' in html(app)
        assert sum(t.value == ROW['other_name'] for t in app.text) == 3
    assert app.chat_input[0].key == 'compose_' + CID
    mocks['get_chat_events'].assert_called_once_with(CID, limit=50)


@pytest.mark.parametrize('actor', [7, 8])
def test_pending_offer_actions_still_belong_only_to_recipient(ui, actor):
    app, _ = open_chat(ui, [{**OFFER, 'sender_id': 8}], actor)
    keys = [c.key for c in app.get('flex_container') if c.key]
    assert 'chat-compact-offer-' + OID in keys
    responses = [b.label for b in app.button if b.label in ('Accept', 'Decline', 'Counteroffer')]
    assert responses == (['Accept', 'Decline', 'Counteroffer'] if actor == 7 else [])
    if actor == 7:
        app.button(key='messaging_offer_counter_' + OID).click().run()
        assert not app.exception
        assert any(b.label == 'Send Counteroffer' for b in app.button)


def test_buy_now_card_keeps_widget_and_places_compact_timestamp_last(ui):
    accepted = {**OFFER, 'status': 'accepted', 'sender_id': 8, 'note': 'Agreed note'}
    app, _ = open_chat(ui, [accepted])
    keys = [c.key for c in app.get('flex_container') if c.key]
    assert 'chat-compact-offer-' + OID in keys
    assert 'chat-time-offer-' + OID in keys
    card = next(c for c in app.get('flex_container') if c.key == 'dm-other-offer-' + OID)
    first = ROW['other_name'].split(' ')[0]
    assert [t.value for t in card.text] == [ROW['other_name'], 'Agreed note', f"You accepted {first}'s offer."]
    # The newly approved redesign includes accepted cards, but not button logic.
    assert not any('2026' in t.value or '·' in t.value for t in card.caption)
    assert card.get('flex_container')[-1].key == 'chat-time-offer-' + OID
    buy = app.button(key='buy_now_' + OID)
    assert not buy.disabled and buy.proto.type == 'primary'  # the buyer can start the purchase
    assert 'width: 78% !important' in messaging_ui.CHAT_CSS
    assert 'padding: 14px 18px !important' in messaging_ui.CHAT_CSS
    assert 'button' not in messaging_ui.COMPACT_CHAT_CSS


def test_inbox_timestamp_and_button_share_right_aligned_action_column(ui):
    app, mocks, _ = ui
    mocks['get_inbox'].return_value = [{**ROW}, {**ROW, 'id': 'second', 'other_name': 'Very long name ' * 20}]
    app.run()
    assert not app.exception
    for row_id in (CID, 'second'):
        actions = next(c for c in app.get('flex_container') if c.key == 'inbox-actions-' + row_id)
        assert len(actions.caption) == 1 and len(actions.button) == 1
        assert actions.button[0].key == 'chat_' + row_id
        assert actions.get('flex_container')[1].key == 'inbox-time-' + row_id
    assert 'align-items: flex-end' in messaging_ui.INBOX_CSS
    assert 'text-align: right; white-space: nowrap' in messaging_ui.INBOX_CSS
    assert 'flex: 0 0 112px' in messaging_ui.INBOX_CSS
    assert '@media (max-width: 640px)' in messaging_ui.INBOX_CSS


def test_compact_css_is_scoped_and_responsive():
    css = messaging_ui.COMPACT_CHAT_CSS
    assert 'width: 68%' in css and 'max-width: 640px' in css
    assert '@media (max-width: 700px)' in css and 'width: 96%' in css
    assert 'padding: 9px 13px' in css
    assert 'st-key-chat-compact-' in css
    assert 'st-key-chat-time-' in css


def test_show_more_keeps_existing_100_event_window_and_query_limits(ui):
    app, mocks, _ = ui
    events = [message(i, 8, '2026-11-19T10:00:00Z') for i in range(100)]
    mocks['get_chat_events'].side_effect = lambda cid, limit: events[-limit:]
    app, mocks = open_chat(ui, events[-50:])
    assert mocks['get_chat_events'].call_args.kwargs == {'limit': 50}
    next(b for b in app.button if b.label == 'Show more history').click().run()
    assert not app.exception
    assert mocks['get_chat_events'].call_args.kwargs == {'limit': 100}
    keys = [c.key for c in app.get('flex_container') if c.key and c.key.startswith('dm-event-')]
    assert len(keys) == 100
    assert not any(b.label == 'Show more history' for b in app.button)
    assert any(c.value == 'Showing the latest 100 chat events.' for c in app.caption)
