from pathlib import Path
from dedupe.mover import execute_move, execute_cleanup


def make_plan(tmp_path: Path, best_name: str = "img.jpg",
              dest_rel: str = "2024/03/15/img.jpg",
              dup_names: list[str] | None = None,
              file_type: str = "image",
              camera: str = "unknown") -> dict:
    best = tmp_path / best_name
    best.write_bytes(b"photo content")
    dups = []
    for name in (dup_names or []):
        d = tmp_path / name
        d.write_bytes(b"photo content")
        dups.append(str(d))
    return {
        "files": {
            file_type: {
                camera: [{
                    "best": str(best),
                    "best_dest": dest_rel,
                    "duplicates": dups,
                }]
            }
        },
        "archives": [],
    }


def test_move_dry_run_does_not_move_files(tmp_path):
    plan = make_plan(tmp_path)
    dest_dir = tmp_path / "dest"
    result = execute_move(plan, dest=str(dest_dir), dry_run=True)
    assert not (dest_dir / "2024/03/15/img.jpg").exists()
    assert (tmp_path / "img.jpg").exists()  # original untouched
    assert result["dry_run"] is True


def test_move_dry_run_reports_planned_moves(tmp_path):
    plan = make_plan(tmp_path)
    dest_dir = tmp_path / "dest"
    result = execute_move(plan, dest=str(dest_dir), dry_run=True)
    assert len(result["planned"]) == 1
    assert result["planned"][0]["from"] == str(tmp_path / "img.jpg")
    assert "2024/03/15/img.jpg" in result["planned"][0]["to"]


def test_move_skips_missing_source_with_warning(tmp_path):
    dest_dir = tmp_path / "dest"
    plan = {
        "files": {
            "image": {
                "unknown": [{
                    "best": str(tmp_path / "nonexistent.jpg"),
                    "best_dest": "2024/01/01/nonexistent.jpg",
                    "duplicates": [],
                }]
            }
        },
        "archives": [],
    }
    result = execute_move(plan, dest=str(dest_dir), dry_run=True)
    assert len(result["warnings"]) == 1
    assert "nonexistent" in result["warnings"][0]


def test_cleanup_dry_run_does_not_move_duplicates(tmp_path):
    plan = make_plan(tmp_path, dup_names=["dup1.jpg", "dup2.jpg"])
    trash_dir = tmp_path / "trash"
    result = execute_cleanup(plan, trash=str(trash_dir), dry_run=True)
    assert not trash_dir.exists()
    assert (tmp_path / "dup1.jpg").exists()
    assert result["dry_run"] is True


def test_cleanup_dry_run_reports_planned_moves(tmp_path):
    plan = make_plan(tmp_path, dup_names=["dup1.jpg"])
    trash_dir = tmp_path / "trash"
    result = execute_cleanup(plan, trash=str(trash_dir), dry_run=True)
    assert len(result["planned"]) == 1
    assert "dup1.jpg" in result["planned"][0]["from"]


def test_cleanup_skips_archive_member_duplicates(tmp_path):
    plan = {
        "files": {
            "image": {
                "unknown": [{
                    "best": str(tmp_path / "img.jpg"),
                    "best_dest": "2024/01/01/img.jpg",
                    "duplicates": ["zip:///archive.zip::vacation/img.jpg"],
                }]
            }
        },
        "archives": [],
    }
    (tmp_path / "img.jpg").write_bytes(b"photo")
    trash_dir = tmp_path / "trash"
    result = execute_cleanup(plan, trash=str(trash_dir), dry_run=True)
    # Archive members can't be moved as loose files — should be noted, not error
    assert len(result["skipped_archive_members"]) == 1
    assert result["planned"] == []


def test_move_flatten_strips_directory(tmp_path):
    plan = make_plan(tmp_path, dest_rel="2024/03/15/img.jpg")
    dest_dir = tmp_path / "dest"
    result = execute_move(plan, dest=str(dest_dir), dry_run=True, flatten=True)
    assert result["planned"][0]["to"] == str(dest_dir / "img.jpg")


def test_move_traverses_multiple_type_and_camera_groups(tmp_path):
    """execute_move should visit all type/camera groups."""
    img1 = tmp_path / "a.jpg"
    img2 = tmp_path / "b.mp4"
    img1.write_bytes(b"photo")
    img2.write_bytes(b"video")
    plan = {
        "files": {
            "image": {
                "iPhone": [{"best": str(img1), "best_dest": "2024/01/01/a.jpg", "duplicates": []}],
            },
            "video": {
                "unknown": [{"best": str(img2), "best_dest": "2024/01/01/b.mp4", "duplicates": []}],
            },
        },
        "archives": [],
    }
    result = execute_move(plan, dest=str(tmp_path / "dest"), dry_run=True)
    assert len(result["planned"]) == 2
