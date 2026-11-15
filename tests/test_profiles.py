"""Tests for the profile rules.

Run them with:  pytest
"""

import io
from datetime import date

import pytest
from PIL import Image

from profiles import (
    MAX_NAME_LENGTH,
    MAX_PHOTO_BYTES,
    PHOTO_SIZE,
    clean_name,
    prepare_photo,
    profile_id_from_text,
    profile_problems,
    public_profile,
)

TODAY = date(2026, 11, 15)
YESTERDAY = date(2026, 11, 14)
NEXT_SUMMER = date(2027, 6, 30)
PROGRAM = "Master's in Finance"


def picture_file(width: int, height: int, kind: str = "PNG") -> bytes:
    """Make a small picture file in memory, like an upload would be."""
    output = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(output, format=kind)
    return output.getvalue()


# --- clean_name: tidy what was typed ------------------------------------------


def test_spaces_around_and_inside_the_name_are_tidied():
    assert clean_name("  Maria   Silva ") == "Maria Silva"


def test_missing_name_becomes_empty_text():
    assert clean_name(None) == ""
    assert clean_name("   ") == ""


# --- profile_problems: may this profile be saved? -----------------------------


def test_complete_profile_has_no_problems():
    assert profile_problems("Maria Silva", PROGRAM, NEXT_SUMMER, TODAY) == []


def test_leaving_date_is_optional():
    assert profile_problems("Maria Silva", PROGRAM, None, TODAY) == []


def test_name_is_required():
    assert profile_problems("", PROGRAM, None, TODAY) == ["Please enter your name."]


def test_name_that_is_too_long_is_rejected():
    long_name = "a" * (MAX_NAME_LENGTH + 1)
    assert len(profile_problems(long_name, PROGRAM, None, TODAY)) == 1
    assert profile_problems("a" * MAX_NAME_LENGTH, PROGRAM, None, TODAY) == []


def test_program_must_be_one_from_the_list():
    assert profile_problems("Maria Silva", None, None, TODAY) == ["Please choose your program."]
    assert profile_problems("Maria Silva", "Made-up program", None, TODAY) == [
        "Please choose your program."
    ]


def test_leaving_date_in_the_past_is_rejected():
    assert len(profile_problems("Maria Silva", PROGRAM, YESTERDAY, TODAY)) == 1


def test_leaving_today_is_allowed():
    assert profile_problems("Maria Silva", PROGRAM, TODAY, TODAY) == []


def test_every_problem_is_reported_at_once():
    assert len(profile_problems("", None, YESTERDAY, TODAY)) == 3


# --- profile_id_from_text: the number in a profile's web address --------------


def test_plain_number_is_accepted():
    assert profile_id_from_text("7") == 7
    assert profile_id_from_text(" 42 ") == 42


def test_anything_that_is_not_a_plain_number_is_rejected():
    assert profile_id_from_text("abc") is None
    assert profile_id_from_text("7abc") is None
    assert profile_id_from_text("7.5") is None
    assert profile_id_from_text("-7") is None
    assert profile_id_from_text("0") is None
    assert profile_id_from_text("²") is None  # looks like a digit, but is not 0-9


def test_missing_number_is_rejected():
    assert profile_id_from_text(None) is None
    assert profile_id_from_text("") is None


# --- public_profile: what other students may see ------------------------------

STORED = {
    "id": 7,
    "email": "12345@novasbe.pt",
    "name": "Maria Silva",
    "program": PROGRAM,
    "leaving_lisbon_on": "2027-06-30",
    "photo_path": "abc.jpg",
    "created_at": "2026-11-15T17:25:03.123456+00:00",
}


def test_public_profile_shows_the_profile_fields():
    shown = public_profile(STORED, TODAY)
    assert shown["id"] == 7
    assert shown["name"] == "Maria Silva"
    assert shown["program"] == PROGRAM
    assert shown["leaving_lisbon_on"] == NEXT_SUMMER
    assert shown["photo_path"] == "abc.jpg"
    assert shown["member_since"] == date(2026, 11, 15)


def test_public_profile_never_contains_the_email():
    shown = public_profile(STORED, TODAY)
    assert "email" not in shown
    assert "12345@novasbe.pt" not in shown.values()


def test_leaving_date_that_has_passed_is_not_shown():
    after_leaving = date(2027, 7, 1)
    assert public_profile(STORED, after_leaving)["leaving_lisbon_on"] is None


def test_leaving_date_is_still_shown_on_the_day_itself():
    assert public_profile(STORED, NEXT_SUMMER)["leaving_lisbon_on"] == NEXT_SUMMER


def test_profile_without_date_and_photo_is_fine():
    stored = {**STORED, "leaving_lisbon_on": None, "photo_path": None}
    shown = public_profile(stored, TODAY)
    assert shown["leaving_lisbon_on"] is None
    assert shown["photo_path"] is None


# --- prepare_photo: make every upload the same small square -------------------


def test_photo_becomes_a_small_square_jpeg():
    result = Image.open(io.BytesIO(prepare_photo(picture_file(1200, 800))))
    assert result.format == "JPEG"
    assert result.size == (PHOTO_SIZE, PHOTO_SIZE)


def test_small_photo_also_becomes_the_same_size():
    result = Image.open(io.BytesIO(prepare_photo(picture_file(50, 90, "JPEG"))))
    assert result.size == (PHOTO_SIZE, PHOTO_SIZE)


def test_file_that_is_not_a_picture_is_rejected():
    with pytest.raises(ValueError):
        prepare_photo(b"this is a text file, not a picture")


def test_empty_file_is_rejected():
    with pytest.raises(ValueError):
        prepare_photo(b"")


def test_file_that_is_too_large_is_rejected():
    with pytest.raises(ValueError):
        prepare_photo(b"x" * (MAX_PHOTO_BYTES + 1))
