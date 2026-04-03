from dedupe.selector import select_best
from dedupe.models import ScannedFile, DuplicateGroup, SelectedFile


def make_file(path: str, mtime: float, source_index: int = 0,
              is_archive_member: bool = False) -> ScannedFile:
    return ScannedFile(path=path, size=100, mtime=mtime, source_index=source_index,
                       is_archive_member=is_archive_member, archive_path=None)


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


def test_loose_file_beats_archive_member_even_with_later_mtime():
    """Loose file must always be best — archive members can't be moved."""
    loose = make_file("/photos/img.jpg", mtime=2000.0)
    archive = make_file("zip:///backup.zip::img.jpg", mtime=1000.0, is_archive_member=True)
    group = DuplicateGroup(hash="abc", files=[archive, loose])
    result = select_best(group)
    assert result.best.path == "/photos/img.jpg"
    assert result.best.is_archive_member is False


def test_canonical_mtime_is_minimum_across_all_copies():
    """canonical_mtime is the earliest mtime regardless of which copy is best."""
    loose = make_file("/photos/img.jpg", mtime=2000.0)
    archive = make_file("zip:///backup.zip::img.jpg", mtime=500.0, is_archive_member=True)
    group = DuplicateGroup(hash="abc", files=[loose, archive])
    result = select_best(group)
    assert result.best.path == "/photos/img.jpg"
    assert result.canonical_mtime == 500.0


def test_canonical_mtime_equals_best_mtime_when_no_archive():
    loose1 = make_file("/a.jpg", mtime=1000.0)
    loose2 = make_file("/b.jpg", mtime=2000.0)
    group = DuplicateGroup(hash="abc", files=[loose1, loose2])
    result = select_best(group)
    assert result.canonical_mtime == 1000.0


def test_dest_file_beats_source_even_with_later_mtime():
    """A file already at dest must always be chosen as best, regardless of mtime."""
    source = make_file("/source/photo.jpg", mtime=1000.0)
    dest = ScannedFile(path="/dest/photo.jpg", size=100, mtime=9999.0,
                       source_index=-1, is_archive_member=False, archive_path=None,
                       is_dest_file=True)
    group = DuplicateGroup(hash="abc", files=[source, dest])
    result = select_best(group)
    assert result.best.path == "/dest/photo.jpg"
    assert result.best.is_dest_file is True
    assert result.duplicates[0].path == "/source/photo.jpg"


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
