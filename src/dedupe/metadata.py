import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .models import FileMetadata

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.raw', '.cr2', '.arw', '.dng'}
VIDEO_EXTENSIONS = {'.mov', '.mp4', '.mpeg', '.mpg', '.avi', '.m4v'}

EXIF_DATE_ORIGINAL = 36867  # DateTimeOriginal tag
EXIF_DATE_DIGITIZED = 36868
EXIF_MAKE = 271
EXIF_MODEL = 272


def _file_type(path: str) -> str:
    # For archive members, extract the real filename
    filename = path.split("::")[-1] if "::" in path else path
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "video"


def _parse_exif_date(date_str: str) -> datetime | None:
    """Parse EXIF date format: '2024:03:15 10:22:01'"""
    try:
        return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _extract_pillow(path: str) -> FileMetadata:
    """Extract metadata from an image using Pillow."""
    from PIL import Image, UnidentifiedImageError

    file_type = _file_type(path)

    # Archive members can't be read by Pillow directly
    if "::" in path:
        return FileMetadata(original_date=None, camera=None, dimensions=None,
                            duration=None, file_type=file_type, date_source="none")

    try:
        with Image.open(path) as img:
            dimensions = f"{img.width}x{img.height}"
            exif = img.getexif()
            if not exif:
                return FileMetadata(original_date=None, camera=None,
                                    dimensions=dimensions, duration=None,
                                    file_type=file_type, date_source="none")

            date_str = exif.get(EXIF_DATE_ORIGINAL) or exif.get(EXIF_DATE_DIGITIZED)
            original_date = _parse_exif_date(date_str)

            make = exif.get(EXIF_MAKE, "")
            model = exif.get(EXIF_MODEL, "")
            camera = f"{make} {model}".strip() or None

            return FileMetadata(
                original_date=original_date,
                camera=camera,
                dimensions=dimensions,
                duration=None,
                file_type=file_type,
                date_source="pillow" if original_date else "none",
            )
    except Exception:
        return FileMetadata(original_date=None, camera=None, dimensions=None,
                            duration=None, file_type=file_type, date_source="none")


def _extract_hachoir(path: str) -> FileMetadata:
    """Extract metadata from a video file using hachoir."""
    from hachoir.parser import createParser
    from hachoir.metadata import extractMetadata

    file_type = _file_type(path)

    if "::" in path:
        return FileMetadata(original_date=None, camera=None, dimensions=None,
                            duration=None, file_type=file_type, date_source="none")
    try:
        parser = createParser(path)
        if not parser:
            return FileMetadata(original_date=None, camera=None, dimensions=None,
                                duration=None, file_type=file_type, date_source="none")
        with parser:
            meta = extractMetadata(parser)
        if not meta:
            return FileMetadata(original_date=None, camera=None, dimensions=None,
                                duration=None, file_type=file_type, date_source="none")

        original_date = None
        date_source = "none"
        if meta.has("creation_date"):
            raw = meta.get("creation_date")
            if hasattr(raw, 'timetuple'):
                original_date = datetime(*raw.timetuple()[:6])
                date_source = "hachoir"

        duration = None
        if meta.has("duration"):
            raw_dur = meta.get("duration")
            if hasattr(raw_dur, 'total_seconds'):
                duration = raw_dur.total_seconds()

        return FileMetadata(
            original_date=original_date,
            camera=None,
            dimensions=None,
            duration=duration,
            file_type=file_type,
            date_source=date_source,
        )
    except Exception:
        return FileMetadata(original_date=None, camera=None, dimensions=None,
                            duration=None, file_type=file_type, date_source="none")


def _parse_exiftool_duration(raw: str | None) -> float | None:
    """Parse exiftool duration string (e.g. '0:00:15' or '15.0 s') to seconds."""
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        pass
    try:
        parts = str(raw).replace(" s", "").split(":")
        parts = [float(p) for p in parts]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0]
    except Exception:
        return None


def _extract_exiftool(path: str) -> FileMetadata:
    """Extract metadata using exiftool (optional system dependency)."""
    file_type = _file_type(path)

    if "::" in path or not shutil.which("exiftool"):
        return FileMetadata(original_date=None, camera=None, dimensions=None,
                            duration=None, file_type=file_type, date_source="none")
    try:
        result = subprocess.run(
            ["exiftool", "-DateTimeOriginal", "-Make", "-Model",
             "-ImageWidth", "-ImageHeight", "-Duration", "-j", path],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        if not data:
            return FileMetadata(original_date=None, camera=None, dimensions=None,
                                duration=None, file_type=file_type, date_source="none")
        d = data[0]

        date_str = d.get("DateTimeOriginal")
        original_date = _parse_exif_date(date_str) if date_str else None

        make = d.get("Make", "")
        model = d.get("Model", "")
        camera = f"{make} {model}".strip() or None

        w = d.get("ImageWidth")
        h = d.get("ImageHeight")
        dimensions = f"{w}x{h}" if w and h else None

        return FileMetadata(
            original_date=original_date,
            camera=camera,
            dimensions=dimensions,
            duration=_parse_exiftool_duration(d.get("Duration")),
            file_type=file_type,
            date_source="exiftool" if original_date else "none",
        )
    except Exception:
        return FileMetadata(original_date=None, camera=None, dimensions=None,
                            duration=None, file_type=file_type, date_source="none")


def extract_metadata(path: str, provider: str = "auto") -> FileMetadata:
    """
    Extract metadata from an image or video file.

    provider: "auto" | "python" | "exiftool"
      - "auto": try python first, fall back to exiftool if no date found and exiftool is available
      - "python": use Pillow (images) or hachoir (video) only
      - "exiftool": use exiftool only
    """
    file_type = _file_type(path)

    if provider == "exiftool":
        return _extract_exiftool(path)

    if file_type == "image":
        result = _extract_pillow(path)
    else:
        result = _extract_hachoir(path)

    if provider == "auto" and result.original_date is None:
        exiftool_result = _extract_exiftool(path)
        if exiftool_result.original_date is not None:
            return exiftool_result

    return result
