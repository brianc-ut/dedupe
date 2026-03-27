import yaml
from pathlib import Path
from datetime import datetime
from dedupe.planner import build_plan, write_plan, read_plan, compute_dest_path
from dedupe.models import ScannedFile, SelectedFile, FileMetadata, ArchiveEntry


def make_scanned(path: str, mtime: float = 1000.0, source_index: int = 0) -> ScannedFile:
    return ScannedFile(path=path, size=100, mtime=mtime, source_index=source_index,
                       is_archive_member=False, archive_path=None)


def make_selected(best_path: str, dup_paths: list[str] | None = None) -> SelectedFile:
    best = make_scanned(best_path)
    dups = [make_scanned(p, mtime=2000.0, source_index=1) for p in (dup_paths or [])]
    return SelectedFile(hash="abc123", best=best, duplicates=dups)


def make_meta(original_date: datetime | None = None, file_type: str = "image") -> FileMetadata:
    return FileMetadata(
        original_date=original_date, camera=None, dimensions=None,
        duration=None, file_type=file_type,
        date_source="pillow" if original_date else "none"
    )


def test_compute_dest_path_with_date():
    f = make_scanned("/photos/IMG.jpg")
    m = make_meta(datetime(2024, 3, 15, 10, 22, 1))
    dest = compute_dest_path(f, m)
    assert dest == "2024/03/15/IMG.jpg"


def test_compute_dest_path_undated():
    f = make_scanned("/photos/IMG.jpg")
    m = make_meta(None)
    dest = compute_dest_path(f, m)
    assert dest == "undated/IMG.jpg"


def test_compute_dest_path_flatten():
    f = make_scanned("/photos/IMG.jpg")
    m = make_meta(datetime(2024, 3, 15))
    dest = compute_dest_path(f, m, flatten=True)
    assert dest == "IMG.jpg"


def test_compute_dest_path_collision():
    f = make_scanned("/photos/IMG.jpg")
    m = make_meta(datetime(2024, 3, 15))
    existing = {"2024/03/15/IMG.jpg"}
    dest = compute_dest_path(f, m, existing_dests=existing)
    assert dest == "2024/03/15/IMG_1.jpg"


def test_compute_dest_path_archive_member():
    f = ScannedFile(path="zip:///archive.zip::vacation/photo.jpg", size=100,
                    mtime=1000.0, source_index=0, is_archive_member=True,
                    archive_path="/archive.zip")
    m = make_meta(datetime(2024, 6, 1))
    dest = compute_dest_path(f, m)
    assert dest == "2024/06/01/photo.jpg"


def test_build_plan_structure():
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15, 10, 22, 1))}
    plan = build_plan(sources=["/photos/**"], selected=selected,
                      metadata=metadata, archives=[])
    assert "files" in plan
    assert "archives" in plan
    assert len(plan["files"]) == 1
    entry = plan["files"][0]
    assert entry["best"] == "/photos/img.jpg"
    assert entry["best_dest"] == "2024/03/15/img.jpg"
    assert entry["duplicates"] == []


def test_build_plan_with_duplicates():
    selected = [make_selected("/a/img.jpg", ["/b/img.jpg", "/c/img.jpg"])]
    metadata = {"/a/img.jpg": make_meta(datetime(2024, 3, 15))}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    assert plan["files"][0]["duplicates"] == ["/b/img.jpg", "/c/img.jpg"]


def test_build_plan_archive_status_fully_covered(tmp_path):
    import zipfile
    zip_path = tmp_path / "backup.zip"
    content = b"photo content"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr("photo.jpg", content)

    loose = make_scanned(str(tmp_path / "photo.jpg"))
    archive_member = ScannedFile(
        path=f"zip://{zip_path}::photo.jpg", size=len(content),
        mtime=1000.0, source_index=0, is_archive_member=True,
        archive_path=str(zip_path)
    )
    selected = [SelectedFile(hash="h1", best=loose, duplicates=[archive_member])]
    metadata = {str(tmp_path / "photo.jpg"): make_meta(datetime(2024, 1, 1))}
    archive_entry = ArchiveEntry(path=str(zip_path), archive_type="zip",
                                  readable=True, contained_files=1)

    plan = build_plan(sources=[], selected=selected, metadata=metadata,
                      archives=[archive_entry])
    arc = plan["archives"][0]
    assert arc["archive_status"] == "fully_covered"


def test_write_and_read_plan_roundtrip(tmp_path):
    plan_path = tmp_path / "plan.yaml"
    selected = [make_selected("/photos/img.jpg", ["/backup/img.jpg"])]
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15))}
    plan = build_plan(sources=["/photos/**"], selected=selected,
                      metadata=metadata, archives=[])
    write_plan(plan, str(plan_path))

    assert plan_path.exists()
    loaded = read_plan(str(plan_path))
    assert loaded["files"][0]["best"] == "/photos/img.jpg"
    assert loaded["files"][0]["duplicates"] == ["/backup/img.jpg"]


def test_undated_files_go_to_undated_folder(tmp_path):
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": make_meta(None)}
    plan = build_plan(sources=["/photos/**"], selected=selected, metadata=metadata, archives=[])
    assert plan["files"][0]["best_dest"].startswith("undated/")


def test_unique_sentinel_hash_output_as_unique(tmp_path):
    # Unique-size files get sentinel hash "unique:{path}" from hasher
    # The planner should output "unique" not the full sentinel
    f = make_scanned("/photos/img.jpg")
    sel = SelectedFile(hash=f"unique:/photos/img.jpg", best=f, duplicates=[])
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15))}
    plan = build_plan(sources=[], selected=[sel], metadata=metadata, archives=[])
    assert plan["files"][0]["hash"] == "unique"
