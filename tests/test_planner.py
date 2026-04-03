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


def make_meta(original_date: datetime | None = None, file_type: str = "image",
              camera: str | None = None, dimensions: str | None = None) -> FileMetadata:
    return FileMetadata(
        original_date=original_date, camera=camera, dimensions=dimensions,
        duration=None, file_type=file_type,
        date_source="pillow" if original_date else "none"
    )


def test_compute_dest_path_with_date():
    f = make_scanned("/photos/IMG.jpg")
    m = make_meta(datetime(2024, 3, 15, 10, 22, 1))
    dest = compute_dest_path(f, m)
    assert dest == "2024/03/15/IMG.jpg"


def test_compute_dest_path_undated_uses_mtime_for_subdir():
    mtime = datetime(2023, 6, 15).timestamp()
    f = make_scanned("/photos/IMG.jpg", mtime=mtime)
    m = make_meta(None)
    dest = compute_dest_path(f, m)
    assert dest == "undated/2023/06/15/IMG.jpg"


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


# --- Nested structure tests ---

def test_build_plan_files_is_nested_dict():
    """files should be a nested dict: type -> camera -> [entries]"""
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": FileMetadata(
        original_date=datetime(2024, 3, 15, 10, 22, 1),
        camera="Apple iPhone 14",
        dimensions=None, duration=None,
        file_type="image", date_source="pillow"
    )}
    plan = build_plan(sources=["/photos/**"], selected=selected,
                      metadata=metadata, archives=[])
    assert isinstance(plan["files"], dict)
    assert "image" in plan["files"]
    assert "Apple iPhone 14" in plan["files"]["image"]
    entries = plan["files"]["image"]["Apple iPhone 14"]
    assert len(entries) == 1
    assert entries[0]["best"] == "/photos/img.jpg"
    assert entries[0]["dest"] == "2024/03/15/img.jpg"


def test_build_plan_entry_uses_dest_not_best_dest():
    """Entry key should be 'dest', not 'best_dest'."""
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15))}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    entry = plan["files"]["image"]["unknown"][0]
    assert "dest" in entry
    assert "best_dest" not in entry


def test_build_plan_no_camera_no_dimensions_uses_unknown():
    """Files with no camera and no dimensions fall back to 'unknown'."""
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15))}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    assert "unknown" in plan["files"]["image"]


def test_build_plan_no_camera_with_dimensions_uses_normalized_dims():
    """Files with no camera but known dimensions group by normalized WxH (larger first)."""
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15), dimensions="3024x4032")}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    assert "4032x3024" in plan["files"]["image"]
    assert "unknown" not in plan["files"]["image"]


def test_build_plan_portrait_and_landscape_same_group():
    """Portrait (3024x4032) and landscape (4032x3024) normalize to the same key."""
    sel_portrait = SelectedFile(hash="h1", best=make_scanned("/a.jpg"), duplicates=[])
    sel_landscape = SelectedFile(hash="h2", best=make_scanned("/b.jpg"), duplicates=[])
    metadata = {
        "/a.jpg": make_meta(datetime(2024, 1, 1), dimensions="3024x4032"),
        "/b.jpg": make_meta(datetime(2024, 1, 2), dimensions="4032x3024"),
    }
    plan = build_plan(sources=[], selected=[sel_portrait, sel_landscape],
                      metadata=metadata, archives=[])
    groups = plan["files"]["image"]
    assert len(groups) == 1
    assert "4032x3024" in groups
    assert len(groups["4032x3024"]) == 2


def test_build_plan_unique_hash_omitted():
    """Entries with hash 'unique' should omit the hash key entirely."""
    f = make_scanned("/photos/img.jpg")
    sel = SelectedFile(hash="unique:/photos/img.jpg", best=f, duplicates=[])
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15))}
    plan = build_plan(sources=[], selected=[sel], metadata=metadata, archives=[])
    entry = plan["files"]["image"]["unknown"][0]
    assert "hash" not in entry


def test_build_plan_real_hash_kept():
    """Non-unique hashes should be present in the entry."""
    selected = [make_selected("/photos/img.jpg", ["/backup/img.jpg"])]
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15))}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    entry = plan["files"]["image"]["unknown"][0]
    assert "hash" in entry
    assert entry["hash"] == "abc123"


def test_build_plan_meta_fields_flattened():
    """Entry should have no 'meta' sub-dict; original_date and date_source at top level."""
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15, 10, 22, 1))}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    entry = plan["files"]["image"]["unknown"][0]
    assert "meta" not in entry
    assert entry["date_source"] == "pillow"
    assert entry["original_date"] == "2024-03-15T10:22:01"


def test_build_plan_undated_entry_has_no_original_date_key():
    """Undated entries should omit both original_date and date_source."""
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": make_meta(None)}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    entry = plan["files"]["image"]["unknown"][0]
    assert "original_date" not in entry
    assert "date_source" not in entry


def test_build_plan_video_type_grouped_separately():
    """Video files should appear under 'video' type key."""
    selected = [make_selected("/videos/clip.mp4")]
    metadata = {"/videos/clip.mp4": make_meta(datetime(2024, 3, 15), file_type="video")}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    assert "video" in plan["files"]
    assert "image" not in plan["files"]


def test_build_plan_multiple_cameras_grouped():
    """Files from different cameras appear under separate camera keys."""
    sel_iphone = SelectedFile(hash="h1", best=make_scanned("/photos/a.jpg"), duplicates=[])
    sel_canon = SelectedFile(hash="h2", best=make_scanned("/photos/b.jpg"), duplicates=[])
    metadata = {
        "/photos/a.jpg": FileMetadata(original_date=datetime(2024, 1, 1), camera="iPhone",
                                      dimensions=None, duration=None,
                                      file_type="image", date_source="pillow"),
        "/photos/b.jpg": FileMetadata(original_date=datetime(2024, 1, 2), camera="Canon",
                                      dimensions=None, duration=None,
                                      file_type="image", date_source="pillow"),
    }
    plan = build_plan(sources=[], selected=[sel_iphone, sel_canon],
                      metadata=metadata, archives=[])
    assert "iPhone" in plan["files"]["image"]
    assert "Canon" in plan["files"]["image"]


def test_build_plan_with_duplicates():
    selected = [make_selected("/a/img.jpg", ["/b/img.jpg", "/c/img.jpg"])]
    metadata = {"/a/img.jpg": make_meta(datetime(2024, 3, 15))}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    entry = plan["files"]["image"]["unknown"][0]
    assert entry["duplicates"] == ["/b/img.jpg", "/c/img.jpg"]


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
    entry = loaded["files"]["image"]["unknown"][0]
    assert entry["best"] == "/photos/img.jpg"
    assert entry["duplicates"] == ["/backup/img.jpg"]


def test_undated_files_go_to_undated_folder():
    mtime = datetime(2023, 6, 15).timestamp()
    f = ScannedFile(path="/photos/img.jpg", size=100, mtime=mtime,
                    source_index=0, is_archive_member=False, archive_path=None)
    sel = SelectedFile(hash="abc123", best=f, duplicates=[])
    metadata = {"/photos/img.jpg": make_meta(None)}
    plan = build_plan(sources=["/photos/**"], selected=[sel], metadata=metadata, archives=[])
    entry = plan["files"]["image"]["unknown"][0]
    assert entry["dest"] == "undated/2023/06/15/img.jpg"


def test_build_plan_date_source_none_omitted():
    """date_source should be omitted from entry when no date was found."""
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": make_meta(None)}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    entry = plan["files"]["image"]["unknown"][0]
    assert "date_source" not in entry


def test_build_plan_empty_duplicates_omitted():
    """duplicates key should be absent when there are no duplicates."""
    selected = [make_selected("/photos/img.jpg")]
    metadata = {"/photos/img.jpg": make_meta(datetime(2024, 3, 15))}
    plan = build_plan(sources=[], selected=selected, metadata=metadata, archives=[])
    entry = plan["files"]["image"]["unknown"][0]
    assert "duplicates" not in entry
