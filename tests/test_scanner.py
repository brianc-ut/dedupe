# tests/test_scanner.py
from pathlib import Path
import pytest
from dedupe.scanner import scan_sources

import zipfile
import tarfile
import io


def test_scan_finds_image_files(tmp_path):
    (tmp_path / "photo.jpg").write_bytes(b"fake jpg")
    files, archives, warnings = scan_sources([str(tmp_path / "**")])
    assert len(files) == 1
    assert files[0].path == str(tmp_path / "photo.jpg")


def test_scan_finds_video_files(tmp_path):
    (tmp_path / "clip.mov").write_bytes(b"fake mov")
    files, archives, warnings = scan_sources([str(tmp_path / "**")])
    assert len(files) == 1


def test_scan_skips_unsupported_extensions(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"fake pdf")
    (tmp_path / "notes.txt").write_bytes(b"text")
    files, archives, warnings = scan_sources([str(tmp_path / "**")])
    assert len(files) == 0


def test_scan_skips_hidden_directories(tmp_path):
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "photo.jpg").write_bytes(b"fake")
    files, archives, warnings = scan_sources([str(tmp_path / "**")])
    assert len(files) == 0


def test_scan_include_hidden_flag(tmp_path):
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "photo.jpg").write_bytes(b"fake")
    files, archives, warnings = scan_sources([str(tmp_path / "**")], include_hidden=True)
    assert len(files) == 1


def test_scan_no_duplicate_paths_across_overlapping_globs(tmp_path):
    (tmp_path / "photo.jpg").write_bytes(b"fake")
    # Two patterns that match the same file
    files, _, _ = scan_sources([str(tmp_path / "**"), str(tmp_path / "*.jpg")])
    paths = [f.path for f in files]
    assert len(paths) == len(set(paths))


def test_scan_assigns_source_index(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "photo.jpg").write_bytes(b"fake")
    (dir_b / "other.jpg").write_bytes(b"fake2")
    files, _, _ = scan_sources([str(dir_a / "**"), str(dir_b / "**")])
    by_index = {f.source_index for f in files}
    assert by_index == {0, 1}


def test_scan_warns_on_empty_glob(tmp_path):
    files, archives, warnings = scan_sources([str(tmp_path / "nonexistent" / "**")])
    assert len(warnings) == 1
    assert "matched no files" in warnings[0]


def test_scan_records_size_and_mtime(tmp_path):
    content = b"hello world"
    (tmp_path / "photo.jpg").write_bytes(content)
    files, _, _ = scan_sources([str(tmp_path / "**")])
    assert files[0].size == len(content)
    assert files[0].mtime > 0


def test_scan_comma_separated_globs(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "photo.jpg").write_bytes(b"fake")
    (dir_b / "other.jpg").write_bytes(b"fake2")
    files, _, _ = scan_sources([f"{dir_a}/**,{dir_b}/**"])
    assert len(files) == 2


def test_scan_detects_unsupported_archive(tmp_path):
    rar = tmp_path / "backup.rar"
    rar.write_bytes(b"fake rar")
    _, archives, _ = scan_sources([str(tmp_path / "**")])
    assert len(archives) == 1
    assert archives[0].archive_type == "unsupported-archive"
    assert not archives[0].readable


def test_scan_inspects_zip_archive(tmp_path):
    zip_path = tmp_path / "photos.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr("vacation/IMG_001.jpg", b"fake jpeg content")
        zf.writestr("vacation/notes.txt", b"not an image")
    files, archives, _ = scan_sources([str(tmp_path / "**")])
    # Only the jpg inside, not the txt
    archive_members = [f for f in files if f.is_archive_member]
    assert len(archive_members) == 1
    assert archive_members[0].path == f"zip://{zip_path}::vacation/IMG_001.jpg"
    assert archives[0].archive_type == "zip"
    assert archives[0].contained_files == 1


def test_scan_inspects_tar_archive(tmp_path):
    tar_path = tmp_path / "photos.tar"
    with tarfile.open(tar_path, 'w') as tf:
        data = b"fake mov content"
        info = tarfile.TarInfo(name="clip.mov")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    files, archives, _ = scan_sources([str(tmp_path / "**")])
    archive_members = [f for f in files if f.is_archive_member]
    assert len(archive_members) == 1
    assert "clip.mov" in archive_members[0].path
    assert archives[0].archive_type == "tar"


def test_scan_unreadable_archive_flagged(tmp_path):
    bad_zip = tmp_path / "corrupt.zip"
    bad_zip.write_bytes(b"not a zip")
    _, archives, warnings = scan_sources([str(tmp_path / "**")])
    assert archives[0].readable is False
    assert len(warnings) == 1
    assert "cannot inspect archive" in warnings[0]


def test_scan_no_duplicate_archive_members_across_overlapping_globs(tmp_path):
    zip_path = tmp_path / "photos.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr("IMG_001.jpg", b"fake jpeg content")
    # Two patterns that both match the same zip file
    files, archives, _ = scan_sources([str(tmp_path / "**"), str(tmp_path / "*.zip")])
    archive_members = [f for f in files if f.is_archive_member]
    paths = [f.path for f in archive_members]
    assert len(paths) == len(set(paths)), "Archive members must not be duplicated"
    assert len(archive_members) == 1


def test_scan_inspects_tar_gz_archive(tmp_path):
    import gzip
    tar_gz_path = tmp_path / "photos.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        data = b"fake jpeg content"
        info = tarfile.TarInfo(name="vacation/IMG_001.jpg")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    tar_gz_path.write_bytes(buf.getvalue())
    files, archives, warnings = scan_sources([str(tmp_path / "**")])
    archive_members = [f for f in files if f.is_archive_member]
    assert len(archive_members) == 1
    assert "IMG_001.jpg" in archive_members[0].path
    assert archives[0].archive_type == "tar"
    assert archives[0].readable is True


def test_scan_archive_with_no_media_files(tmp_path):
    zip_path = tmp_path / "docs.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr("readme.txt", b"just text")
        zf.writestr("notes.txt", b"more text")
    files, archives, _ = scan_sources([str(tmp_path / "**")])
    archive_members = [f for f in files if f.is_archive_member]
    assert len(archive_members) == 0
    assert len(archives) == 1
    assert archives[0].contained_files == 0
    assert archives[0].readable is True
