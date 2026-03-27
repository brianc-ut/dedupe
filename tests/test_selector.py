from dedupe.selector import select_best
from dedupe.models import ScannedFile, DuplicateGroup, SelectedFile


def make_file(path: str, mtime: float, source_index: int = 0) -> ScannedFile:
    return ScannedFile(path=path, size=100, mtime=mtime, source_index=source_index,
                       is_archive_member=False, archive_path=None)


def test_single_file_is_its_own_best():
    files = [make_file("/a/photo.jpg", mtime=1000.0)]
    group = DuplicateGroup(hash="abc123", files=files)
    result = select_best(group)
    assert isinstance(result, SelectedFile)
    assert result.best.path == "/a/photo.jpg"
    assert result.duplicates == []


def test_selects_earliest_mtime():
    files = [
        make_file("/b/photo.jpg", mtime=2000.0),
        make_file("/a/photo.jpg", mtime=1000.0),  # earlier
    ]
    group = DuplicateGroup(hash="abc123", files=files)
    result = select_best(group)
    assert result.best.path == "/a/photo.jpg"
    assert len(result.duplicates) == 1
    assert result.duplicates[0].path == "/b/photo.jpg"


def test_source_index_tiebreaker_on_equal_mtime():
    files = [
        make_file("/b/photo.jpg", mtime=1000.0, source_index=1),
        make_file("/a/photo.jpg", mtime=1000.0, source_index=0),  # lower index wins
    ]
    group = DuplicateGroup(hash="abc123", files=files)
    result = select_best(group)
    assert result.best.path == "/a/photo.jpg"


def test_selected_file_preserves_hash():
    files = [make_file("/a/photo.jpg", mtime=1000.0)]
    group = DuplicateGroup(hash="deadbeef", files=files)
    result = select_best(group)
    assert result.hash == "deadbeef"


def test_all_duplicates_are_accounted_for():
    files = [
        make_file("/a.jpg", mtime=1000.0),
        make_file("/b.jpg", mtime=2000.0),
        make_file("/c.jpg", mtime=3000.0),
    ]
    group = DuplicateGroup(hash="abc", files=files)
    result = select_best(group)
    assert result.best.path == "/a.jpg"
    dup_paths = {d.path for d in result.duplicates}
    assert dup_paths == {"/b.jpg", "/c.jpg"}
