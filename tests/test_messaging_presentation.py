"""Messaging presentation helpers: no network, auth provider or database."""

from urllib.parse import unquote
import xml.etree.ElementTree as ET

import pytest

from messaging_ui import avatar_background, accepted_offer_description


def fallback_svg(background):
    return ET.fromstring(unquote(background.split('url("data:image/svg+xml,', 1)[1].split('")', 1)[0]))


@pytest.mark.parametrize("name,initials", [("Mia Silva", "MS"), ("Ava", "A"), ("", "?"), ("  Theo  Pereira  Costa ", "TP")])
def test_initials_avatar_needs_no_photo(name, initials):
    svg = fallback_svg(avatar_background(name, None))
    assert svg.find('{http://www.w3.org/2000/svg}text').text == initials


def test_signed_photo_layers_above_initials_for_browser_load_failure_fallback():
    url = "https://photos.example.invalid/profile.jpg?download=false"
    background = avatar_background("Mia Silva", url)
    assert background.startswith(f'url("{url}"), url("data:image/svg+xml,')
    assert fallback_svg(background).find('{http://www.w3.org/2000/svg}text').text == "MS"


@pytest.mark.parametrize("url", [None, "", "javascript:alert(1)", "data:text/html,invalid", "https://user:pass@example.invalid/p.jpg", "https://[bad"])
def test_untrusted_photo_schemes_use_initials(url):
    assert avatar_background("Mia", url).startswith('url("data:image/svg+xml,')


def test_avatar_cannot_inject_html_or_stylesheet():
    background = avatar_background('<script> break', 'https://photos.example.invalid/x");}</style><script>bad</script>')
    assert '<script>' not in background and '</style>' not in background
    svg = fallback_svg(background)
    assert len(list(svg)) == 2  # rectangle and text, never injected markup


@pytest.mark.parametrize("actor,sender,expected", [
    (7, 7, "The seller has accepted your offer."),
    (7, 8, "You have accepted the seller's counteroffer."),
    (8, 7, "You have accepted the buyer's offer."),
    (8, 8, "The buyer has accepted your offer."),
])
def test_accepted_offer_copy_follows_conversation_roles(actor, sender, expected):
    assert accepted_offer_description({"sender_id": sender}, {"buyer_id": 7, "own_profile_id": actor}) == expected
