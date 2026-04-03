import hashlib
import io
import tarfile
import zipfile
from pathlib import Path
from dedupe.hasher import group_by_hash, _read_content
from dedupe.models import ScannedFile


def make_file(path: str, content: bytes, tmp_path: Path, source_index: int = 0) -> ScannedFile:
    p = tmp_path / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return ScannedFile(
        path=str(p), size=len(content), mtime=p.stat().st_mtime,
        source_index=source_index, is_archive_member=False, archive_path=None
    )


def test_unique_sizes_produce_singleton_groups(tmp_path):
    f1 = make_file("a.jpg", b"aaa", tmp_path)
    f2 = make_file("b.jpg", b"bbbb", tmp_path)
    groups = group_by_hash([f1, f2])
    assert all(len(g.files) == 1 for g in groups)


def test_identical_content_grouped(tmp_path):
    content = b"identical photo content"
    f1 = make_file("a/photo.jpg", content, tmp_path)
    f2 = make_file("b/photo.jpg", content, tmp_path)
    groups = group_by_hash([f1, f2])
    dup_groups = [g for g in groups if len(g.files) > 1]
    assert len(dup_groups) == 1
    assert len(dup_groups[0].files) == 2


def test_same_size_different_content_not_grouped(tmp_path):
    f1 = make_file("a.jpg", b"content_a", tmp_path)
    f2 = make_file("b.jpg", b"content_b", tmp_path)
    groups = group_by_hash([f1, f2])
    assert all(len(g.files) == 1 for g in groups)


def test_hash_is_sha256_hex(tmp_path):
    content = b"same content"
    f1 = make_file("a.jpg", content, tmp_path)
    f2 = make_file("b.jpg", content, tmp_path)
    groups = group_by_hash([f1, f2])
    dup = next(g for g in groups if len(g.files) > 1)
    assert dup.hash == hashlib.sha256(content).hexdigest()


def test_empty_input_returns_empty(tmp_path):
    groups = group_by_hash([])
    assert groups == []


def test_group_by_hash_calls_progress_for_every_file(tmp_path):
    """progress_callback should be called once per file."""
    f1 = make_file("a.jpg", b"aaa", tmp_path)
    f2 = make_file("b.jpg", b"bbbb", tmp_path)
    f3 = make_file("c.jpg", b"aaa", tmp_path)  # duplicate of f1
    seen = []
    group_by_hash([f1, f2, f3], progress_callback=seen.append)
    assert len(seen) == 3


def test_group_by_hash_progress_callback_optional(tmp_path):
    """group_by_hash should work fine with no progress_callback."""
    f1 = make_file("a.jpg", b"aaa", tmp_path)
    groups = group_by_hash([f1])
    assert len(groups) == 1


def test_archive_member_hashed_correctly(tmp_path):
    # Create a zip with a known-content file
    content = b"archive member content"
    zip_path = tmp_path / "photos.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr("photo.jpg", content)

    # Also create the same content as a loose file
    loose = make_file("loose.jpg", content, tmp_path)
    archive_member = ScannedFile(
        path=f"zip://{zip_path}::photo.jpg",
        size=len(content), mtime=zip_path.stat().st_mtime,
        source_index=0, is_archive_member=True, archive_path=str(zip_path)
    )

    groups = group_by_hash([loose, archive_member])
    dup_groups = [g for g in groups if len(g.files) > 1]
    assert len(dup_groups) == 1  # loose and archive member are duplicates


def test_read_content_tar_member(tmp_path):
    content = b"tar member content"
    tar_path = tmp_path / "photos.tar"
    with tarfile.open(tar_path, 'w') as tf:
        info = tarfile.TarInfo(name="photo.jpg")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))

    member = ScannedFile(
        path=f"tar://{tar_path}::photo.jpg",
        size=len(content), mtime=tar_path.stat().st_mtime,
        source_index=0, is_archive_member=True, archive_path=str(tar_path)
    )
    result = _read_content(member)
    assert result == content
