"""Photos: check and clean up listing photos before they are stored.

For every photo we:
1. Open it with Pillow (the image library Streamlit already installs). This proves
   it really is a JPG or PNG, not another file that was simply renamed.
2. Turn it the right way up. Phones save the rotation as a hidden flag, so
   photos can otherwise appear sideways.
3. Shrink it so the longest side is at most MAX_SIDE pixels.
4. Save a fresh copy WITHOUT the hidden metadata. Phone photos often contain the
   GPS position where they were taken - often the seller's home.

A 4 MB phone photo usually ends up around 200-500 KB, so pages load much faster.
"""

from io import BytesIO

from PIL import Image, ImageOps

MIN_PHOTOS = 1
MAX_PHOTOS = 5
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per photo, before shrinking
MAX_SIDE = 1600  # pixels, longest side
JPEG_QUALITY = 82  # looks the same as the original on screen

# Refuse "decompression bombs": tiny files that expand to enormous images in memory.
Image.MAX_IMAGE_PIXELS = 40_000_000


class PhotoError(ValueError):
    """One or more photos can't be used. `errors` lists every problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def check_photo_count(count: int) -> list[str]:
    if count < MIN_PHOTOS:
        return ["Add at least one photo."]
    if count > MAX_PHOTOS:
        return [f"A listing can have at most {MAX_PHOTOS} photos."]
    return []


def _has_transparency(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)


def prepare_photo(data: bytes, label: str = "Photo") -> bytes:
    """Return a checked, upright, smaller copy of the photo without metadata."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoError([f"{label} is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."])
    try:
        img = Image.open(BytesIO(data))
        if img.format not in ("JPEG", "PNG"):
            raise PhotoError([f"{label} must be a JPG or PNG image."])
        img.load()
    except PhotoError:
        raise
    except Exception:  # not an image, damaged, or far too large
        raise PhotoError([f"{label} couldn't be read. Try another photo."]) from None

    img = ImageOps.exif_transpose(img)  # apply the rotation flag
    img.thumbnail((MAX_SIDE, MAX_SIDE))  # only ever shrinks, keeps proportions

    out = BytesIO()
    if _has_transparency(img):
        img.save(out, format="PNG", optimize=True)
    else:
        img.convert("RGB").save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


def prepare_photos(photos: list[bytes]) -> list[bytes]:
    """prepare_photo() for several photos, reporting every bad one at once."""
    prepared, errors = [], []
    for number, data in enumerate(photos, start=1):
        label = "Photo" if len(photos) == 1 else f"Photo {number}"
        try:
            prepared.append(prepare_photo(data, label))
        except PhotoError as exc:
            errors += exc.errors
    if errors:
        raise PhotoError(errors)
    return prepared
