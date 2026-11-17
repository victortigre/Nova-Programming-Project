"""Tests for photo clean-up: resizing, rotation, removing GPS data, rejecting bad files."""

from io import BytesIO

import pytest
from PIL import Image

from photos import MAX_SIDE, PhotoError, prepare_photo, prepare_photos

GPS_TAG = 0x8825
ORIENTATION_TAG = 0x0112


def jpeg(width, height, exif=None) -> bytes:
    out = BytesIO()
    Image.new("RGB", (width, height), (30, 120, 200)).save(
        out, format="JPEG", quality=95, exif=exif or Image.Exif())
    return out.getvalue()


def open_image(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


def test_big_photo_is_shrunk_keeping_proportions():
    assert open_image(prepare_photo(jpeg(4000, 3000))).size == (MAX_SIDE, 1200)


def test_small_photo_is_not_enlarged():
    assert open_image(prepare_photo(jpeg(400, 300))).size == (400, 300)


def test_gps_location_is_removed():
    exif = Image.Exif()
    exif[GPS_TAG] = {1: "N", 2: (38.0, 41.0, 0.0)}
    original = jpeg(800, 600, exif)
    assert GPS_TAG in open_image(original).getexif()
    assert GPS_TAG not in open_image(prepare_photo(original)).getexif()


def test_sideways_phone_photo_is_turned_upright():
    exif = Image.Exif()
    exif[ORIENTATION_TAG] = 6  # the "rotate 90°" flag phones write
    result = open_image(prepare_photo(jpeg(800, 600, exif)))
    assert result.size == (600, 800)
    assert ORIENTATION_TAG not in result.getexif()


def test_png_is_accepted_and_transparency_kept():
    out = BytesIO()
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(out, format="PNG")
    assert open_image(prepare_photo(out.getvalue())).format == "PNG"


def test_fake_image_is_rejected():
    with pytest.raises(PhotoError, match="couldn't be read"):
        prepare_photo(b"\xff\xd8\xff" + b"not a photo" * 10)


def test_other_formats_are_rejected():
    out = BytesIO()
    Image.new("RGB", (10, 10)).save(out, format="GIF")
    with pytest.raises(PhotoError, match="JPG or PNG"):
        prepare_photo(out.getvalue())


def test_too_large_upload_is_rejected():
    with pytest.raises(PhotoError, match="larger than 10 MB"):
        prepare_photo(b"\x00" * (10 * 1024 * 1024 + 1))


def test_every_bad_photo_is_reported():
    with pytest.raises(PhotoError) as exc:
        prepare_photos([jpeg(10, 10), b"junk", b"junk"])
    assert exc.value.errors == ["Photo 2 couldn't be read. Try another photo.",
                                "Photo 3 couldn't be read. Try another photo."]
