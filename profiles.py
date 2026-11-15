"""Profiles: the rules for what a student may put on their profile.

Nothing in this file talks to the database or to the screen. It only
checks and tidies what a person typed in, so the rules can be tested on
their own (tests/test_profiles.py).
"""

import io
from datetime import date

from PIL import Image, ImageOps, UnidentifiedImageError

# The choices in the "Program" box. Change this list if a program is missing.
PROGRAMS = [
    "Bachelor's in Economics",
    "Bachelor's in Management",
    "Master's in Economics",
    "Master's in Finance",
    "Master's in Management",
    "International Master's in Management",
    "Master's in Business Analytics",
    "Master's in Impact Entrepreneurship and Innovation",
    "Master's in International Development and Public Policy",
    "MBA",
    "PhD",
    "Exchange student",
    "Other",
]

MAX_NAME_LENGTH = 60
PHOTO_SIZE = 400  # stored photos are 400 x 400 pixels
MAX_PHOTO_MB = 10
MAX_PHOTO_BYTES = MAX_PHOTO_MB * 1024 * 1024


def clean_name(name: str | None) -> str:
    """Remove spaces at both ends and double spaces in the middle."""
    return " ".join((name or "").split())


def profile_problems(
    name: str, program: str | None, leaving_lisbon_on: date | None, today: date
) -> list[str]:
    """Return what is wrong with a profile, as messages for the person.

    An empty list means the profile may be saved. The leaving date is
    optional, so None is fine there.
    """
    problems = []

    if not name:
        problems.append("Please enter your name.")
    elif len(name) > MAX_NAME_LENGTH:
        problems.append(f"Your name can be at most {MAX_NAME_LENGTH} characters long.")

    if program not in PROGRAMS:
        problems.append("Please choose your program.")

    if leaving_lisbon_on is not None and leaving_lisbon_on < today:
        problems.append("The day you leave Lisbon cannot be in the past.")

    return problems


def profile_id_from_text(text: str | None) -> int | None:
    """Turn the profile number from a web address into a number, or None.

    A profile page is opened with an address that ends in ?id=7. Anybody
    can type anything there, so only plain digits are accepted.
    """
    text = (text or "").strip()
    if not text.isascii() or not text.isdigit():
        return None
    number = int(text)
    return number if number > 0 else None


def public_profile(profile: dict, today: date) -> dict:
    """Return the parts of a stored profile that other students may see.

    The email is left out on purpose: students reach each other through
    the app, not by email. A leaving date that has already passed is left
    out too, because it no longer says anything useful.
    """
    leaving_lisbon_on = None
    if profile.get("leaving_lisbon_on"):
        leaving_lisbon_on = date.fromisoformat(profile["leaving_lisbon_on"])
        if leaving_lisbon_on < today:
            leaving_lisbon_on = None

    return {
        "id": profile["id"],
        "name": profile["name"],
        "program": profile["program"],
        "leaving_lisbon_on": leaving_lisbon_on,
        "photo_path": profile.get("photo_path"),
        # The database stores a full timestamp; its first 10 characters are the date.
        "member_since": date.fromisoformat(profile["created_at"][:10]),
    }


def prepare_photo(file_bytes: bytes) -> bytes:
    """Turn an uploaded picture into a small square JPEG.

    Whatever people upload (a huge phone photo, a PNG, a sideways picture),
    we store the same thing: 400 x 400 pixels, upright, as JPEG. Raises
    ValueError with a message for the person if the file is not a picture.
    """
    if len(file_bytes) > MAX_PHOTO_BYTES:
        raise ValueError(f"That picture is too large. Please use one under {MAX_PHOTO_MB} MB.")

    try:
        picture = Image.open(io.BytesIO(file_bytes))
        picture = ImageOps.exif_transpose(picture)  # turn phone photos upright
        picture = ImageOps.fit(picture.convert("RGB"), (PHOTO_SIZE, PHOTO_SIZE))
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as error:
        raise ValueError("That file is not a picture we can read.") from error

    output = io.BytesIO()
    picture.save(output, format="JPEG", quality=85)
    return output.getvalue()
