"""Compact Inbox presentation; authenticated transport remains fully mocked."""
import pytest

import database
import messaging_repository as repository
from messaging_ui import inbox_activity_preview, inbox_timestamp
from test_messaging_ui import ui, ROW, CID

SECOND = '22222222-2222-4222-8222-222222222222'
REAL_INBOX = repository.get_inbox


def markup(app):
    return '\n'.join(x.proto.body for x in app.get('html'))


def test_compact_rows_keep_actions_refresh_and_no_asking_price(ui):
    app, mocks, _ = ui
    mocks['get_inbox'].return_value = [
        {**ROW, 'other_name': 'Jonathan', 'listing_title_snapshot': 'Surfboard', 'unread': True},
        {**ROW, 'id': SECOND, 'listing_id': None, 'other_name': 'Seller'},
    ]
    app.run()
    assert not app.exception
    containers = app.get('flex_container')
    listing = next(c for c in containers if c.key == 'inbox-list')
    assert len([c for c in listing.get('flex_container') if c.key and c.key.startswith('inbox-row-')]) == 2
    assert len(listing.get('divider')) == 1
    # The name is the clickable button above the summary (no dot); unread shows as
    # the row highlight and the violet counter, like WhatsApp.
    assert any(b.label == 'Jonathan' and b.key == 'openname_' + CID for b in app.button)
    assert '🔵' not in markup(app)
    assert markup(app).count('inbox-summary inbox-unread') == 1
    assert markup(app).count('class="inbox-count"') == 1
    assert 'Surfboard' in markup(app) and 'Listing no longer available' in markup(app)
    assert not app.image
    assert 'inbox-avatar' in markup(app)
    assert 'data:image/svg+xml,' in markup(app)
    assert not any('€20' in c.value for c in app.caption)
    for row in listing.get('flex_container'):
        if row.key and row.key.startswith('inbox-row-'):
            left, right = row.get('column')
            # The left column holds only the name button (which also opens the chat).
            assert left.button and all(b.key.startswith('openname_') for b in left.button)
            assert right.button[0].label == 'Open chat'
            assert right.caption
    # No "Refresh inbox" button: the page updates by itself (app.py, live_updates).
    assert not any(c.key == 'inbox-toolbar' for c in containers)
    assert not any(b.label == 'Refresh inbox' for b in app.button)
    app.button(key='chat_' + CID).click().run()
    assert app.chat_input and not app.exception


@pytest.mark.parametrize('sender', [7, 8])
@pytest.mark.parametrize('newer_message', [True, False])
def test_repository_chronology_and_compact_preview(ui, monkeypatch, sender, newer_message):
    app, mocks, _ = ui
    message = {'id': 1, 'sender_id': sender, 'body': 'Latest text',
               'created_at': '2026-11-21T12:00:00+00:00' if newer_message else '2026-11-21T10:00:00+00:00'}
    offer = {'id': SECOND, 'sender_id': 7, 'amount_cents': 2500, 'status': 'accepted',
             'created_at': '2026-11-21T09:00:00+00:00', 'responded_at': '2026-11-21T11:00:00+00:00'}
    older = {**ROW, 'id': SECOND, 'created_at': '2026-11-19T10:00:00+00:00'}
    # The older chat has its own (older) message so it still appears, sorting below ROW.
    older_message = {'id': 9, 'sender_id': 8, 'body': 'Older text', 'created_at': '2026-11-19T10:00:00+00:00'}
    monkeypatch.setattr(repository, 'get_inbox', REAL_INBOX)
    monkeypatch.setattr(database, 'messaging_actor_profile', lambda email: {'id': 7, 'rules_accepted_at': 'yes'})
    monkeypatch.setattr(database, 'messaging_unread_conversations', lambda actor: [])
    monkeypatch.setattr(database, 'messaging_inbox', lambda actor: [
        {'conversation': older, 'other_name': 'Older', 'last_message': older_message, 'last_offer': None},
        {'conversation': ROW, 'other_name': 'Newest', 'last_message': message, 'last_offer': offer},
    ])
    app.run()
    assert not app.exception
    assert [b.key for b in app.button if b.label == 'Open chat'] == ['chat_' + CID, 'chat_' + SECOND]
    assert ('Latest text' in markup(app)) == newer_message
    assert ('Offer: €25.00 · Accepted' in markup(app)) == (not newer_message)
    expected = inbox_timestamp(message['created_at'] if newer_message else offer['responded_at'])
    assert any(c.value == expected for c in app.caption)


@pytest.mark.parametrize('status,parent,expected', [
    ('pending', None, 'Offer: €25.00 · Pending'),
    ('pending', CID, 'Counteroffer: €25.00 · Pending'),
    ('accepted', None, 'Offer: €25.00 · Accepted'),
    ('declined', CID, 'Counteroffer: €25.00 · Declined'),
])
def test_offer_previews_describe_creation_counter_and_responses(status, parent, expected):
    activity = {'type': 'offer', 'sender_id': 8, 'amount_cents': 2500,
                'status': status, 'parent_offer_id': parent}
    assert inbox_activity_preview(activity, 7) == expected


def test_preview_escapes_untrusted_text_and_keeps_full_one_line_content(ui):
    app, mocks, _ = ui
    text = '<script>bad</script> ' + 'Long message ' * 40
    mocks['get_inbox'].return_value = [{**ROW, 'other_name': '<b>Name</b>',
        'last_activity': {'type': 'message', 'sender_id': 8, 'body': text,
                          'created_at': ROW['created_at']}}]
    app.run()
    assert not app.exception
    html = markup(app)
    assert '<script>bad</script>' not in html
    assert '&lt;script&gt;bad&lt;/script&gt;' in html
    assert '&lt;b&gt;Name&lt;/b&gt;' in html
    assert 'text-overflow: ellipsis' in html and 'white-space: nowrap' in html
    assert 'Long message ' * 40 in html


@pytest.mark.parametrize('url', [None, 'https://photos.example.invalid/avatar.jpg'])
def test_inbox_avatars_keep_summary_chronology_and_navigation(ui, url):
    app, mocks, _ = ui
    mocks['get_inbox'].return_value = [{**ROW, 'other_name': 'Mia Silva', 'other_photo_url': url,
        'last_activity': {'type': 'message', 'sender_id': 8, 'body': 'Most recent message',
                          'created_at': ROW['created_at']}}]
    app.run()
    assert not app.exception
    mocks['get_inbox'].assert_called_once_with(include_photos=True)
    html = markup(app)
    assert 'width: 46px; height: 46px' in html and 'border-radius: 50%' in html
    assert 'aria-label="Mia Silva profile picture"' in html
    assert 'data:image/svg+xml,' in html
    if url:
        assert url in html  # Real photo and layered initials fallback both present.
    # The name is the clickable button above the summary; the preview stays inline.
    assert any(b.label == 'Mia Silva' and b.key == 'openname_' + CID for b in app.button)
    assert 'Most recent message' in html
    assert 'text-overflow: ellipsis' in html
    app.button(key='chat_' + CID).click().run()
    assert app.chat_input and not app.exception
