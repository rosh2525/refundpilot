"""Bounded, metadata-free image evidence; no filenames or filesystem writes."""
import base64
import binascii
import hashlib
from dataclasses import dataclass
from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
MAX_IMAGE_EDGE = 1600
MAX_BASE64_LENGTH = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
SUPPORTED_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG"}


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedEvidence:
    image_bytes: bytes
    mime_type: str
    sha256: str
    size_bytes: int
    width: int
    height: int


def normalize_image(image_base64: str, media_type: str) -> NormalizedEvidence:
    """Decode strict base64, verify JPEG/PNG pixels, and strip all metadata.

    The encoded request and decoded pixel count are checked before decompression.
    The client-declared MIME type must match the actual image format. Animation,
    malformed/truncated content, and oversized normalized results are rejected.
    """
    if media_type not in SUPPORTED_TYPES:
        raise EvidenceError("Upload a JPEG or PNG image.")
    if not isinstance(image_base64, str) or not image_base64 or len(image_base64) > MAX_BASE64_LENGTH:
        raise EvidenceError("The image must be at most 2 MiB.")
    try:
        raw = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EvidenceError("The image is not valid base64.") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise EvidenceError("The image must be at most 2 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format != SUPPORTED_TYPES[media_type]:
                    raise EvidenceError("The image content does not match its JPEG/PNG media type.")
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise EvidenceError("The image must be at most 12 megapixels.")
                if getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                    raise EvidenceError("Animated images are not supported.")
                source.verify()
            with Image.open(BytesIO(raw)) as source:
                source.load()
                ImageOps.exif_transpose(source, in_place=True)
                # Shrink before converting/copying pixels to avoid multiple
                # full-resolution buffers on the small free hosting instance.
                source.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
                mode = "RGBA" if media_type == "image/png" and ("A" in source.getbands() or "transparency" in source.info) else "RGB"
                pixels = source if source.mode == mode else source.convert(mode)
                clean = Image.new(mode, pixels.size)
                clean.paste(pixels)
                output = BytesIO()
                if media_type == "image/jpeg":
                    clean.save(output, format="JPEG", quality=90)
                else:
                    clean.save(output, format="PNG", compress_level=6)
                normalized = output.getvalue()
                width, height = clean.size
    except EvidenceError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise EvidenceError("The image is malformed or cannot be safely decoded.") from exc
    if len(normalized) > MAX_IMAGE_BYTES:
        raise EvidenceError("The normalized image exceeds 2 MiB; upload a smaller image.")
    return NormalizedEvidence(normalized, media_type, hashlib.sha256(normalized).hexdigest(), len(normalized), width, height)
