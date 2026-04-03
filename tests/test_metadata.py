from pathlib import Path
from datetime import datetime
from dedupe.metadata import extract_metadata, extract_metadata_batch, _needs_exiftool_fallback
from dedupe.models import FileMetadata


def make_meta(file_type="image", date=None, dimensions=None, duration=None):
    return FileMetadata(
        original_date=date, camera=None, dimensions=dimensions,
        duration=duration, file_type=file_type,
        date_source="pillow" if date else "none",
    )


def make_jpeg_with_exif(tmp_path, name="photo.jpg", date_str="2024:03:15 10:22:01"):
    from PIL import Image
    import io
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    exif_data = img.getexif()
    exif_data[36867] = date_str
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_data.tobytes())
    f = tmp_path / name
    f.write_bytes(buf.getvalue())
    return f


def make_jpeg_no_exif(tmp_path, name="bare.jpg"):
    from PIL import Image
    import io
    img = Image.new("RGB", (10, 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    f = tmp_path / name
    f.write_bytes(buf.getvalue())
    return f


# --- _needs_exiftool_fallback ---

def test_needs_exiftool_fallback_image_has_dimensions_no_date():
    """Pillow opened image (has dimensions) but no date — do NOT call exiftool."""
    result = make_meta(file_type="image", dimensions="10x10")
    assert _needs_exiftool_fallback(result) is False


def test_needs_exiftool_fallback_image_no_dimensions():
    """Pillow couldn't open image (no dimensions) — DO call exiftool."""
    result = make_meta(file_type="image", dimensions=None)
    assert _needs_exiftool_fallback(result) is True


def test_needs_exiftool_fallback_image_has_date():
    """Image already has a date — no fallback needed regardless."""
    result = make_meta(file_type="image", date=datetime(2024, 1, 1), dimensions="10x10")
    assert _needs_exiftool_fallback(result) is False


def test_needs_exiftool_fallback_video_has_duration():
    """hachoir got duration — do NOT call exiftool."""
    result = make_meta(file_type="video", duration=15.0)
    assert _needs_exiftool_fallback(result) is False


def test_needs_exiftool_fallback_video_no_duration_no_date():
    """hachoir got nothing — DO call exiftool."""
    result = make_meta(file_type="video", duration=None, date=None)
    assert _needs_exiftool_fallback(result) is True


def test_needs_exiftool_fallback_video_has_date_no_duration():
    """Video has date (no duration) — no fallback needed."""
    result = make_meta(file_type="video", date=datetime(2024, 1, 1), duration=None)
    assert _needs_exiftool_fallback(result) is False


# --- extract_metadata (single-file, tightened fallback) ---

def test_unreadable_file_returns_null_metadata(tmp_path):
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"not a real jpeg")
    result = extract_metadata(str(f), provider="python")
    assert isinstance(result, FileMetadata)
    assert result.original_date is None
    assert result.date_source == "none"


def test_image_file_type_by_extension(tmp_path):
    for ext in [".jpg", ".jpeg", ".png", ".heic", ".tiff", ".raw", ".cr2", ".arw", ".dng"]:
        f = tmp_path / f"photo{ext}"
        f.write_bytes(b"fake")
        result = extract_metadata(str(f), provider="python")
        assert result.file_type == "image", f"Expected image for {ext}"


def test_video_file_type_by_extension(tmp_path):
    for ext in [".mov", ".mp4", ".mpeg", ".mpg", ".avi", ".m4v"]:
        f = tmp_path / f"clip{ext}"
        f.write_bytes(b"fake")
        result = extract_metadata(str(f), provider="python")
        assert result.file_type == "video", f"Expected video for {ext}"


def test_pillow_extracts_exif_date(tmp_path):
    f = make_jpeg_with_exif(tmp_path)
    result = extract_metadata(str(f), provider="python")
    assert result.original_date == datetime(2024, 3, 15, 10, 22, 1)
    assert result.date_source == "pillow"


def test_auto_provider_does_not_call_exiftool_when_pillow_has_dimensions(tmp_path):
    """Valid image Pillow can open → no exiftool fallback even if no date."""
    f = make_jpeg_no_exif(tmp_path)
    result = extract_metadata(str(f), provider="auto")
    # Pillow opened it (has dimensions), so exiftool should not be tried
    assert result.dimensions is not None
    assert result.date_source == "none"  # no exiftool, no date from Pillow


def test_auto_provider_falls_back_gracefully(tmp_path):
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"not a real jpeg")
    result = extract_metadata(str(f), provider="auto")
    assert result.original_date is None
    assert result.date_source in ("none", "exiftool")


def test_metadata_for_archive_member_uses_path_extension(tmp_path):
    result = extract_metadata("zip:///archive.zip::vacation/photo.jpg", provider="python")
    assert result.file_type == "image"


# --- extract_metadata_batch ---

def test_extract_metadata_batch_returns_result_for_every_path(tmp_path):
    """Batch function returns a FileMetadata for every input path."""
    f1 = make_jpeg_with_exif(tmp_path, "a.jpg")
    f2 = make_jpeg_no_exif(tmp_path, "b.jpg")
    f3 = tmp_path / "c.jpg"
    f3.write_bytes(b"not a real jpeg")

    results = extract_metadata_batch([str(f1), str(f2), str(f3)])
    assert set(results.keys()) == {str(f1), str(f2), str(f3)}
    assert all(isinstance(v, FileMetadata) for v in results.values())


def test_extract_metadata_batch_correct_dates(tmp_path):
    """Batch results match single-file extraction."""
    f1 = make_jpeg_with_exif(tmp_path, "dated.jpg")
    f2 = make_jpeg_no_exif(tmp_path, "undated.jpg")

    results = extract_metadata_batch([str(f1), str(f2)])
    assert results[str(f1)].original_date == datetime(2024, 3, 15, 10, 22, 1)
    assert results[str(f1)].date_source == "pillow"
    assert results[str(f2)].original_date is None


def test_extract_metadata_batch_empty_input():
    assert extract_metadata_batch([]) == {}
