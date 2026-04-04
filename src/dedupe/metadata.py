import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import FileMetadata

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.raw', '.cr2', '.arw', '.dng'}
VIDEO_EXTENSIONS = {'.mov', '.mp4', '.mpeg', '.mpg', '.avi', '.m4v'}

EXIF_DATE_ORIGINAL = 36867  # DateTimeOriginal tag
EXIF_DATE_DIGITIZED = 36868
EXIF_MAKE = 271
EXIF_MODEL = 272
EXIF_GPS_IFD = 34853       # GPS info IFD pointer


def _gps_rational(val) -> float:
    """Convert a Pillow GPS rational value (IFDRational or (num, den) tuple) to float."""
    if hasattr(val, 'numerator'):
        return float(val.numerator) / float(val.denominator) if val.denominator else 0.0
    if isinstance(val, tuple) and len(val) == 2:
        return float(val[0]) / float(val[1]) if val[1] else 0.0
    return float(val)


def _parse_gps_ifd(gps: dict) -> tuple[float | None, float | None]:
    """Extract decimal lat/lon from a Pillow GPS IFD dict. Returns (lat, lon) or (None, None)."""
    try:
        lat_vals = gps.get(2)  # GPSLatitude: (deg, min, sec)
        lat_ref  = gps.get(1, 'N')
        lon_vals = gps.get(4)  # GPSLongitude
        lon_ref  = gps.get(3, 'E')
        if not lat_vals or not lon_vals or len(lat_vals) < 3 or len(lon_vals) < 3:
            return None, None

        def to_dec(vals, ref):
            d = _gps_rational(vals[0]) + _gps_rational(vals[1]) / 60.0 + _gps_rational(vals[2]) / 3600.0
            return -d if ref in ('S', 'W') else d

        return to_dec(lat_vals, lat_ref), to_dec(lon_vals, lon_ref)
    except Exception:
        return None, None


def _file_type(path: str) -> str:
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


# Supported filename date patterns, tried in order:
#   IMG_YYYYMMDD_HHMMSS[mmm]      — Android camera (e.g. IMG_20180311_162025257.jpg)
#   YYYY-MM-DD_HH-MM-SS[_mmm]     — dash-separated (e.g. 2023-09-09_09-23-40_832.heic)
_FILENAME_DATE_PATTERNS = [
    re.compile(r'IMG_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\d*'),
    re.compile(r'(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})(?:_\d+)?'),
]


def _parse_filename_date(path: str) -> datetime | None:
    """Extract datetime from a recognized filename date pattern. Returns None if no match."""
    raw = path.split("::")[-1] if "::" in path else path
    stem = Path(raw).stem
    for pattern in _FILENAME_DATE_PATTERNS:
        m = pattern.search(stem)
        if m:
            try:
                y, mo, d, h, mi, s = (int(x) for x in m.groups())
                return datetime(y, mo, d, h, mi, s)
            except ValueError:
                continue
    return None


def _apply_filename_date(result: FileMetadata, path: str) -> FileMetadata:
    """If result has no date, try to parse one from the filename."""
    if result.original_date is not None:
        return result
    dt = _parse_filename_date(path)
    if dt is None:
        return result
    return FileMetadata(
        original_date=dt,
        camera=result.camera,
        dimensions=result.dimensions,
        duration=result.duration,
        file_type=result.file_type,
        date_source="filename",
        latitude=result.latitude,
        longitude=result.longitude,
    )


def _needs_exiftool_fallback(result: FileMetadata) -> bool:
    """
    Return True only when the Python reader got no structural metadata at all.

    Images: Pillow always sets dimensions if it can open the file. No dimensions
            means it couldn't parse the file — exiftool may succeed.
    Videos: hachoir sets duration when it can parse the container. Neither
            duration nor date means it failed entirely.
    """
    if result.file_type == "image":
        return result.dimensions is None
    else:
        return result.original_date is None and result.duration is None


def _extract_pillow(path: str) -> FileMetadata:
    """Extract metadata from an image using Pillow."""
    from PIL import Image

    file_type = _file_type(path)

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

            lat, lon = _parse_gps_ifd(exif.get_ifd(EXIF_GPS_IFD))

            return FileMetadata(
                original_date=original_date,
                camera=camera,
                dimensions=dimensions,
                duration=None,
                file_type=file_type,
                date_source="pillow" if original_date else "none",
                latitude=lat,
                longitude=lon,
            )
    except Exception:
        return FileMetadata(original_date=None, camera=None, dimensions=None,
                            duration=None, file_type=file_type, date_source="none")


def _extract_hachoir(path: str) -> FileMetadata:
    """Extract metadata from a video file using hachoir."""
    import logging
    from hachoir.parser import createParser
    from hachoir.metadata import extractMetadata

    file_type = _file_type(path)

    if "::" in path:
        return FileMetadata(original_date=None, camera=None, dimensions=None,
                            duration=None, file_type=file_type, date_source="none")
    try:
        logging.getLogger("hachoir").setLevel(logging.CRITICAL)
        from hachoir.core.log import log as hachoir_log
        hachoir_log.use_print = False
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


def _extract_exiftool_batch(paths: list[str]) -> dict[str, FileMetadata]:
    """Run exiftool once on all given paths, return results keyed by path."""
    if not paths or not shutil.which("exiftool"):
        return {}
    try:
        result = subprocess.run(
            ["exiftool", "-DateTimeOriginal", "-Make", "-Model",
             "-ImageWidth", "-ImageHeight", "-Duration",
             "-GPSLatitude#", "-GPSLongitude#",
             "-j", "-q"] + paths,
            capture_output=True, text=True, timeout=120,
        )
        data = json.loads(result.stdout)
    except Exception:
        return {}

    results = {}
    for d in data:
        source_file = d.get("SourceFile", "")
        if not source_file:
            continue
        file_type = _file_type(source_file)
        date_str = d.get("DateTimeOriginal")
        original_date = _parse_exif_date(date_str) if date_str else None
        make = d.get("Make", "")
        model = d.get("Model", "")
        camera = f"{make} {model}".strip() or None
        w = d.get("ImageWidth")
        h = d.get("ImageHeight")
        dimensions = f"{w}x{h}" if w and h else None
        try:
            lat = float(d["GPSLatitude"]) if d.get("GPSLatitude") is not None else None
            lon = float(d["GPSLongitude"]) if d.get("GPSLongitude") is not None else None
        except (TypeError, ValueError):
            lat, lon = None, None
        results[source_file] = FileMetadata(
            original_date=original_date,
            camera=camera,
            dimensions=dimensions,
            duration=_parse_exiftool_duration(d.get("Duration")),
            file_type=file_type,
            date_source="exiftool" if original_date else "none",
            latitude=lat,
            longitude=lon,
        )
    return results


def _extract_python(path: str) -> FileMetadata:
    """Run Pillow (images) or hachoir (video) for a single file."""
    if _file_type(path) == "image":
        return _extract_pillow(path)
    return _extract_hachoir(path)


def extract_metadata(path: str, provider: str = "auto") -> FileMetadata:
    """
    Extract metadata from a single file.

    provider: "auto" | "python" | "exiftool"
      - "auto": Python first; exiftool fallback only when Python got no structural
                metadata (image has no dimensions, or video has no duration/date)
      - "python": Pillow (images) or hachoir (video) only
      - "exiftool": exiftool only
    """
    if provider == "exiftool":
        results = _extract_exiftool_batch([path])
        return results.get(path, FileMetadata(
            original_date=None, camera=None, dimensions=None,
            duration=None, file_type=_file_type(path), date_source="none",
        ))

    result = _extract_python(path)

    if provider == "auto" and _needs_exiftool_fallback(result) and "::" not in path:
        exiftool_results = _extract_exiftool_batch([path])
        exiftool_result = exiftool_results.get(path)
        if exiftool_result and exiftool_result.original_date is not None:
            return _apply_filename_date(exiftool_result, path)

    return _apply_filename_date(result, path)


def extract_metadata_batch(
    paths: list[str],
    provider: str = "auto",
    max_workers: int = 8,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, FileMetadata]:
    """
    Extract metadata for multiple files in parallel.

    Python extraction runs concurrently via ThreadPoolExecutor.
    Exiftool (when needed) runs once in a single batch subprocess.
    progress_callback is called with each path as its Python result completes.
    """
    if not paths:
        return {}

    # Step 1: parallel Python extraction
    results: dict[str, FileMetadata] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {
            executor.submit(_extract_python, p): p
            for p in paths
        }
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                results[path] = future.result()
            except Exception:
                results[path] = FileMetadata(
                    original_date=None, camera=None, dimensions=None,
                    duration=None, file_type=_file_type(path), date_source="none",
                )
            if progress_callback:
                progress_callback(path)

    if provider == "python":
        return results

    # Step 2: single batch exiftool for files that need it
    needs_exiftool = [
        p for p in paths
        if "::" not in p and _needs_exiftool_fallback(results[p])
    ]
    if needs_exiftool:
        exiftool_results = _extract_exiftool_batch(needs_exiftool)
        for path, exif_meta in exiftool_results.items():
            if exif_meta.original_date is not None:
                results[path] = exif_meta

    # Step 3: filename date fallback for anything still undated
    for path in paths:
        results[path] = _apply_filename_date(results[path], path)

    return results
