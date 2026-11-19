"""Storage-independent messaging rules."""

import pytest

from messaging import (
    MAX_MESSAGE_LENGTH,
    conversation_key,
    is_conversation_participant,
    require_conversation_participant,
    validate_conversation_participants,
    validate_message,
)


def test_message_preserves_internal_whitespace_and_unicode():
    assert validate_message(" \nOlá 👋  Sofia!\nCan we meet?\t ") == "Olá 👋  Sofia!\nCan we meet?"


def test_message_length_boundary_after_trimming():
    assert validate_message(" " + "é" * MAX_MESSAGE_LENGTH + " ") == "é" * MAX_MESSAGE_LENGTH
    with pytest.raises(ValueError, match="at most"):
        validate_message("x" * (MAX_MESSAGE_LENGTH + 1))


@pytest.mark.parametrize("body", ["", " \n\t", "\u2003", None, 123, b"hello"])
def test_invalid_message_is_rejected(body):
    with pytest.raises(ValueError):
        validate_message(body)


def test_different_participants_are_valid():
    validate_conversation_participants(1, 2)
    for actor in (1, 2):
        assert is_conversation_participant(actor, 1, 2)
        require_conversation_participant(actor, 1, 2)


def test_self_conversation_is_rejected():
    with pytest.raises(ValueError, match="yourself"):
        validate_conversation_participants(1, 1)
    assert not is_conversation_participant(1, 1, 1)


@pytest.mark.parametrize("invalid", [None, True, False, 0, -1, "1", 1.0])
def test_invalid_identities_fail_closed(invalid):
    for buyer, seller in ((invalid, 2), (1, invalid)):
        with pytest.raises(ValueError):
            validate_conversation_participants(buyer, seller)
        assert not is_conversation_participant(1, buyer, seller)
    assert not is_conversation_participant(invalid, 1, 2)
    with pytest.raises(ValueError, match="Conversation unavailable"):
        require_conversation_participant(invalid, 1, 2)


def test_outsider_is_denied():
    assert not is_conversation_participant(3, 1, 2)
    with pytest.raises(ValueError, match="Conversation unavailable"):
        require_conversation_participant(3, 1, 2)


def test_conversation_key_is_one_per_buyer_per_listing():
    assert conversation_key(10, 1) == conversation_key(10, 1)
    assert conversation_key(10, 1) != conversation_key(10, 2)
    assert conversation_key(10, 1) != conversation_key(11, 1)


@pytest.mark.parametrize("invalid", [None, True, 0, -1, "desk-demo", 1.0])
def test_invalid_conversation_key_is_rejected(invalid):
    with pytest.raises(ValueError):
        conversation_key(invalid, 1)
    with pytest.raises(ValueError):
        conversation_key(10, invalid)
