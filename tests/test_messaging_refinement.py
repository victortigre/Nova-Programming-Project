"""Stage 1 formatting/header tests; transport and authentication are mocked."""
from datetime import datetime

import pytest

from messaging_ui import inbox_timestamp
from test_messaging_ui import ui, ROW, CID


@pytest.mark.parametrize('stamp,now,expected', [
    ('2026-07-05T23:30:00Z', '2026-07-06T00:45:00+01:00', '00:30'),
    ('2026-07-05T22:59:00Z', '2026-07-06T00:00:00+01:00', 'Yesterday'),
    ('2026-01-01T23:59:00Z', '2026-01-02T00:00:00Z', 'Yesterday'),
    ('2025-12-31T12:00:00Z', '2026-01-02T00:00:00Z', '31 Dec'),
    ('2026-07-05T23:30:00Z', '2026-07-05T20:00:00-04:00', '00:30'),
    # Spring forward: 00:59 UTC -> 00:59 Lisbon, 01:00 UTC -> 02:00 Lisbon.
    ('2026-03-29T00:59:00Z', '2026-03-29T12:00:00Z', '00:59'),
    ('2026-03-29T01:00:00Z', '2026-03-29T12:00:00Z', '02:00'),
    # Fall back: the two distinct UTC instants share the local 01:30 label.
    ('2026-10-25T00:30:00Z', '2026-10-25T12:00:00Z', '01:30'),
    ('2026-10-25T01:30:00Z', '2026-10-25T12:00:00Z', '01:30'),
    # Yesterday is a calendar comparison, including 23/25-hour local days.
    ('2026-03-28T23:30:00Z', '2026-03-29T23:30:00Z', '28 Mar'),
    ('2026-03-29T01:30:00Z', '2026-03-29T23:30:00Z', 'Yesterday'),
    ('2026-10-24T23:30:00Z', '2026-10-26T00:00:00Z', 'Yesterday'),
])
def test_lisbon_inbox_timestamp(stamp, now, expected):
    assert inbox_timestamp(stamp, now=datetime.fromisoformat(now.replace('Z', '+00:00'))) == expected


def test_naive_timestamp_is_not_guessed_from_server_timezone():
    with pytest.raises(ValueError, match='Timezone-aware'):
        inbox_timestamp('2026-07-06T00:30:00', now=datetime.fromisoformat('2026-07-06T01:00:00+01:00'))
    with pytest.raises(ValueError, match='Timezone-aware'):
        inbox_timestamp('2026-07-06T00:30:00Z', now=datetime(2026, 7, 6))


def markup(app):
    return '\n'.join(item.proto.body for item in app.get('html'))


def test_inbox_name_listing_and_preview_are_stacked(ui):
    app, mocks, _ = ui
    mocks['get_inbox'].return_value = [{**ROW, 'unread': True, 'last_activity': {
        'type': 'message', 'sender_id': 8, 'body': 'Latest activity', 'created_at': ROW['created_at']}}]
    app.run()
    assert not app.exception
    html = markup(app)
    assert '<strong>🔵 Test participant</strong></div><div class="inbox-listing">Test listing snapshot</div>' in html
    assert html.index('Test listing snapshot') < html.index('Latest activity')
    assert 'width: 46px; height: 46px' in html
    assert 'data:image/svg+xml,' in html


@pytest.mark.parametrize('photo', [None, 'https://photos.example.invalid/profile.jpg'])
def test_chat_header_toolbar_refresh_and_back_preserve_state(ui, photo):
    app, mocks, _ = ui
    mocks['get_conversation_details'].return_value = {**ROW, 'other_photo_url': photo}
    app.run()
    app.button(key='chat_' + CID).click().run()
    assert not app.exception
    toolbar = next(c for c in app.get('flex_container') if c.key == 'chat-toolbar')
    left, right = toolbar.get('column')[0], toolbar.get('column')[-1]
    assert left.button[0].label == '← Back to Inbox'
    assert right.button[0].label == 'Refresh chat'
    header = next(c for c in app.get('flex_container') if c.key == 'chat-participant-header')
    assert header.subheader[0].value == ROW['other_name']
    assert [c.value for c in header.caption] == [ROW['listing_title_snapshot'], '€20.00']
    assert 'data:image/svg+xml,' in markup(app)
    if photo:
        assert photo in markup(app)
    assert app.get('divider')
    mocks['mark_read'].assert_called_once_with(CID)
    before = mocks['get_chat_events'].call_count
    right.button[0].click().run()
    assert not app.exception and mocks['get_chat_events'].call_count == before + 1
    assert app.session_state['messaging_selected'] == CID
    assert app.chat_input[0].key == 'compose_' + CID
    next(b for b in app.button if b.label == '← Back to Inbox').click().run()
    assert not app.exception and not app.chat_input


def test_compact_reserved_notice_preserves_restrictions_and_messaging(ui):
    app, mocks, _ = ui
    mocks['get_conversation_details'].return_value = {**ROW, 'listing_status': 'reserved'}
    app.run()
    app.button(key='chat_' + CID).click().run()
    assert not app.exception
    assert any('This listing is reserved.' in c.value and 'Negotiation is unavailable' in c.value for c in app.caption)
    assert not any(b.label in ('Send Offer', 'Accept', 'Decline', 'Counteroffer') for b in app.button)
    app.chat_input[0].set_value('Still messaging').run()
    assert not app.exception
    assert mocks['send_message'].call_args.args[:2] == (CID, 'Still messaging')
