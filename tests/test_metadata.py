from pathlib import Path
from datetime import datetime
from dedupe.metadata import extract_metadata
from dedupe.models import FileMetadata


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
    # Create a minimal JPEG with EXIF DateTimeOriginal using Pillow
    from PIL import Image
    import io

    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    exif_data = img.getexif()
    exif_data[36867] = "2024:03:15 10:22:01"  # DateTimeOriginal tag
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_data.tobytes())
    f = tmp_path / "photo_with_exif.jpg"
    f.write_bytes(buf.getvalue())

    result = extract_metadata(str(f), provider="python")
    assert result.original_date == datetime(2024, 3, 15, 10, 22, 1)
    assert result.date_source == "pillow"


def test_auto_provider_falls_back_gracefully(tmp_path):
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"not a real jpeg")
    result = extract_metadata(str(f), provider="auto")
    assert result.original_date is None
    assert result.date_source in ("none", "exiftool")


def test_metadata_for_archive_member_uses_path_extension(tmp_path):
    # Archive members have paths like zip:///path.zip::photo.jpg
    # We can't read them directly for metadata — metadata returns defaults
    result = extract_metadata("zip:///archive.zip::vacation/photo.jpg", provider="python")
    assert result.file_type == "image"
