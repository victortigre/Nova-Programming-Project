"""Run the main app with mocked navigation, identity, settings and storage."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import accounts
import database
import deals
import ui


@pytest.fixture
def navigation(monkeypatch):
    user = SimpleNamespace(is_logged_in=True, to_dict=lambda: {
        "email": "student@novasbe.pt", "email_verified": True,
    })
    monkeypatch.setattr(st, "user", user)
    identity = MagicMock(side_effect=lambda: user.to_dict())
    monkeypatch.setattr(accounts, "logged_in_user", identity)
    monkeypatch.setattr(accounts, "admin_emails", lambda: ["admin@novasbe.pt"])
    monkeypatch.setattr(database, "_client", MagicMock(side_effect=AssertionError("No live database")))
    monkeypatch.setattr(database, "database_is_set_up", lambda: True)
    profile = MagicMock(return_value={"id": 7, "rules_accepted_at": "2026-11-20"})
    monkeypatch.setattr(database, "get_profile", profile)
    monkeypatch.setattr(deals, "to_do", lambda db, email: {"sales": 2, "purchases": 1})
    monkeypatch.setattr(ui, "apply_style", lambda: None)
    pages = []

    def make_page(path, **kwargs):
        page = SimpleNamespace(path=path, url_path=kwargs.get("url_path", Path(path).stem), **{
            key: value for key, value in kwargs.items() if key != "url_path"
        })
        pages.append(page)
        return page

    monkeypatch.setattr(st, "Page", make_page)
    nav = MagicMock(side_effect=lambda choices, **kwargs: SimpleNamespace(
        url_path=choices[0].url_path, run=lambda: None,
    ))
    monkeypatch.setattr(st, "navigation", nav)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    # Synthetic configuration only, stored in the test instance, never on disk.
    app.secrets["auth"] = {"auth0": {
        "client_id": "test-client", "client_secret": "test-only",
        "server_metadata_url": "https://example.invalid/.well-known/openid-configuration",
    }}
    return app, user, profile, pages, nav, identity


def test_messages_added_without_removing_existing_navigation(navigation):
    app, _, _, pages, nav, identity = navigation
    app.run()
    assert not app.exception
    assert [page.title for page in pages] == [
        "Browse", "Sell an item", "My listings", "My purchases (1)", "Sales (2)",
        "Messages", "My profile", "House rules", "Student profile", "Report", "Welcome",
    ]
    messages = next(page for page in pages if page.title == "Messages")
    assert messages.path == "views/messaging.py"
    assert nav.call_args.kwargs == {"position": "top"}
    assert identity.called


@pytest.mark.parametrize("state", ["logged_out", "unverified", "wrong_domain", "blocked", "no_profile", "unfinished"])
def test_messages_unavailable_before_access_requirements(navigation, state):
    app, user, profile, pages, _, _ = navigation
    if state == "logged_out":
        user.is_logged_in = False
    elif state in ("unverified", "wrong_domain"):
        user.to_dict = lambda: {
            "email": "outsider@example.com" if state == "wrong_domain" else "student@novasbe.pt",
            "email_verified": state != "unverified",
        }
    elif state == "blocked":
        profile.return_value = {"id": 7, "blocked_at": "2026-11-20", "rules_accepted_at": "2026-11-20"}
    elif state == "no_profile":
        profile.return_value = None
    else:
        profile.return_value = {"id": 7, "rules_accepted_at": None}
    app.run()
    assert not app.exception
    assert not any(page.path == "views/messaging.py" for page in pages)
    if state in ("no_profile", "unfinished"):
        assert [page.title for page in pages] == ["Welcome"]


def test_admin_navigation_is_preserved(navigation):
    app, user, _, pages, _, _ = navigation
    user.to_dict = lambda: {"email": "admin@novasbe.pt", "email_verified": True}
    app.run()
    assert not app.exception
    assert any(page.title == "Messages" for page in pages)
    assert any(page.title == "Admin" for page in pages)
