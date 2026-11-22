"""Page-scoped card presentation with fictional in-memory data and photo URLs."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import accounts
import deals
import payment_ui
from fake_database import FakeDatabase
from deal_helpers import start_purchase

ROOT = Path(__file__).resolve().parents[1]
SELLER, BUYER = 'seller@novasbe.pt', 'buyer@novasbe.pt'
PHOTO = 'https://photos.example.invalid/listing.jpg'


@pytest.fixture
def shop(monkeypatch):
    db = FakeDatabase()
    seller = db.add_profile(SELLER, 'Seller')
    buyer = db.add_profile(BUYER, 'Buyer')
    photo = MagicMock(return_value=PHOTO)
    monkeypatch.setattr(db, 'listing_photo_url', photo, raising=False)
    monkeypatch.setitem(sys.modules, 'database', db)
    monkeypatch.setattr(payment_ui, 'database', db)
    monkeypatch.setattr(accounts, 'logged_in_user', lambda: None)
    current = {'email': SELLER}
    monkeypatch.setattr(accounts, 'verified_nova_email', lambda user: current['email'])
    monkeypatch.setattr(st, 'page_link', MagicMock())  # Navigation is outside isolated page tests.
    return SimpleNamespace(db=db, seller=seller, buyer=buyer, photo=photo, current=current)


def item(shop, *, photos=True, price=2000):
    return shop.db.insert_listing({'seller_id': shop.seller['id'], 'title': 'Desk lamp',
        'description': 'Original description', 'photo_paths': ['actual-stored-path.jpg'] if photos else [],
        'price_cents': price, 'category': 'Furniture', 'pickup_area': 'Carcavelos'})['id']


def run_page(name):
    app = AppTest.from_file(str(ROOT / 'views' / name), default_timeout=30).run()
    assert not app.exception
    return app


def markup(app):
    return '\n'.join(e.proto.body for e in app.get('html'))


@pytest.mark.parametrize('status,actions', [
    ('active', {'reserve', 'sold', 'edit', 'delete'}),
    ('reserved', {'sold', 'relist', 'edit', 'delete'}),
    ('sold', {'relist', 'edit', 'delete'}),
])
def test_listing_thumbnail_and_existing_status_actions(shop, status, actions):
    lid = item(shop)
    shop.db.listings[lid]['status'] = status
    app = run_page('my_listings.py')
    shop.photo.assert_called_once_with('actual-stored-path.jpg')
    assert app.image[0].value[0] == PHOTO
    assert {b.key.split('-')[0] for b in app.button if b.key and b.key.endswith('-' + str(lid))} == actions
    assert app.button(key=f'edit-{lid}').proto.icon == ':material/edit:'
    if status == 'active':
        assert app.button(key=f'reserve-{lid}').proto.icon == ':material/event:'
    if status != 'sold':
        assert app.button(key=f'sold-{lid}').proto.icon == ':material/check:'
    assert any(p.proto.popover.label == 'Delete' for p in app.get('popover'))
    assert any(m.value == '**Desk lamp**' for m in app.markdown)
    assert any(c.value == '€20.00 · Furniture · Carcavelos' for c in app.caption)


def test_listing_actions_keep_confirmation_and_state_changes(shop):
    lid = item(shop, photos=False, price=0)
    app = run_page('my_listings.py')
    assert 'Listing photo unavailable' in markup(app)
    app.button(key=f'reserve-{lid}').click().run()
    assert not app.exception and shop.db.get_listing(lid)['status'] == 'reserved'
    app.button(key=f'relist-{lid}').click().run()
    assert not app.exception and shop.db.get_listing(lid)['status'] == 'active'
    app.button(key=f'sold-{lid}').click().run()
    assert not app.exception and shop.db.get_listing(lid)['status'] == 'sold'
    assert any(p.proto.popover.label == 'Delete' for p in app.get('popover'))
    assert app.button(key=f'delete-{lid}').label == 'Yes, delete'
    assert shop.db.get_listing(lid) is not None  # Trigger still needs confirmation.
    app.button(key=f'delete-{lid}').click().run()
    assert not app.exception and shop.db.get_listing(lid) is None


@pytest.mark.parametrize('status,price,photos', [
    ('requested', 2000, True), ('accepted', 2000, True),
    ('completed', 2000, True), ('completed', 0, False),
    ('declined', 2000, False), ('cancelled', 2000, False),
])
def test_purchase_states_keep_information_and_add_correct_photo(shop, monkeypatch, status, price, photos):
    lid = item(shop, photos=photos, price=price)
    rid = shop.db.insert_request({'listing_id': lid, 'buyer_id': shop.buyer['id'], 'status': status})['id']
    if status == 'accepted':
        shop.db.requests[rid].update(paid_at='2026-11-22T12:00:00+00:00', payment_method='bank')
    shop.current['email'] = BUYER
    app = run_page('purchases.py')
    cards = [c for c in app.get('flex_container') if c.key == f'purchase-main-card-{rid}']
    assert len(cards) == 1
    left, right = cards[0].get('column')[:2]
    assert not left.button and any('**Desk lamp**' in m.value for m in right.markdown)
    assert any(c.value == 'Seller: Seller' for c in right.caption)
    if photos:
        shop.photo.assert_called_once_with('actual-stored-path.jpg')
        assert left.image[0].value[0] == PHOTO
    else:
        shop.photo.assert_not_called()
        assert 'Listing photo unavailable' in markup(app)
    if status == 'requested':
        assert app.button(key=f'cancel-{rid}').label == 'Cancel request'
    if status == 'accepted':
        assert any('Waiting for the seller to confirm' in i.value for i in right.info)
    if status == 'completed':
        assert any('Paid and confirmed by the seller' in m.value for m in right.markdown)
        assert any(b.label == 'Send rating' for b in app.button)


@pytest.mark.parametrize('mode', ['no_path', 'no_url', 'sign_error'])
def test_purchase_photo_fallback_never_hides_payment_instructions(shop, mode):
    lid = item(shop, photos=mode != 'no_path')
    deal = start_purchase(shop.db, lid, BUYER)
    if mode == 'no_url':
        shop.photo.return_value = None
    if mode == 'sign_error':
        shop.photo.side_effect = RuntimeError('private provider detail')
    shop.current['email'] = BUYER
    app = run_page('purchases.py')
    assert 'Listing photo unavailable' in markup(app)
    assert not app.image
    assert 'private provider detail' not in markup(app)
    assert any('paid' in b.label.lower() for b in app.button)
    assert any('bank transfer' in w.value.lower() for w in app.warning)
    assert shop.db.get_request(deal['id'])['status'] == 'accepted'


def test_only_page_scoped_styles_and_natural_card_height():
    for name, prefix in [('my_listings.py', 'my-listing-'), ('purchases.py', 'purchase-')]:
        source = (ROOT / 'views' / name).read_text(encoding='utf-8')
        css = source.split('st.html("""<style>', 1)[1].split('</style>""")', 1)[0]
        assert '#FFFFFF' in css and 'aspect-ratio: 4 / 3' in css
        assert '@media (max-width: 700px)' in css and 'flex-wrap: wrap' in css
        assert 'height:' not in css and 'position: absolute' not in css
        assert 'st-key-' + prefix in css
        assert 'stApp' not in css and 'stAlert' not in css
