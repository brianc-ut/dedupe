from dedupe.models import ScannedFile, ArchiveEntry, DuplicateGroup, SelectedFile, FileMetadata
from datetime import datetime

def test_scanned_file_fields():
    f = ScannedFile(path="/a/b.jpg", size=100, mtime=1000.0,
                    source_index=0, is_archive_member=False, archive_path=None)
    assert f.path == "/a/b.jpg"
    assert not f.is_archive_member

def test_archive_member_scanned_file():
    f = ScannedFile(path="zip:///a/b.zip::photos/img.jpg", size=50, mtime=1000.0,
                    source_index=0, is_archive_member=True, archive_path="/a/b.zip")
    assert f.is_archive_member
    assert f.archive_path == "/a/b.zip"

def test_duplicate_group_fields():
    f = ScannedFile(path="/a/b.jpg", size=100, mtime=1000.0,
                    source_index=0, is_archive_member=False, archive_path=None)
    g = DuplicateGroup(hash="abc123", files=[f])
    assert g.hash == "abc123"
    assert len(g.files) == 1

def test_selected_file_fields():
    best = ScannedFile(path="/a/b.jpg", size=100, mtime=1000.0,
                       source_index=0, is_archive_member=False, archive_path=None)
    dup = ScannedFile(path="/backup/b.jpg", size=100, mtime=2000.0,
                      source_index=1, is_archive_member=False, archive_path=None)
    s = SelectedFile(hash="abc123", best=best, duplicates=[dup])
    assert s.best.path == "/a/b.jpg"
    assert len(s.duplicates) == 1

def test_archive_entry_fields():
    a = ArchiveEntry(path="/a/b.zip", archive_type="zip", readable=True, contained_files=12)
    assert a.archive_type == "zip"
    assert a.contained_files == 12

def test_file_metadata_fields():
    m = FileMetadata(original_date=datetime(2024, 3, 15), camera="iPhone 13",
                     dimensions="4032x3024", duration=None,
                     file_type="image", date_source="pillow")
    assert m.file_type == "image"
    assert m.date_source == "pillow"
