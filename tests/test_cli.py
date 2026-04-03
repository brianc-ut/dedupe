import yaml
from pathlib import Path
from typer.testing import CliRunner
from dedupe.cli import app

runner = CliRunner()


def _count_files(plan: dict) -> int:
    """Count total file entries across all type/camera groups."""
    return sum(
        len(entries)
        for camera_groups in plan["files"].values()
        for entries in camera_groups.values()
    )


def _iter_entries(plan: dict):
    """Iterate over all file entries in the nested plan structure."""
    for camera_groups in plan["files"].values():
        for entries in camera_groups.values():
            yield from entries


def test_plan_requires_source_and_output(tmp_path):
    result = runner.invoke(app, ["plan"])
    assert result.exit_code != 0


def test_plan_creates_yaml_file(tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"fake jpeg")
    output = tmp_path / "plan.yaml"

    result = runner.invoke(app, [
        "plan",
        "--source", str(tmp_path / "**"),
        "--output", str(output),
    ])

    assert result.exit_code == 0, result.output
    assert output.exists()
    plan = yaml.safe_load(output.read_text())
    assert "files" in plan
    assert _count_files(plan) == 1


def test_plan_multiple_sources(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "photo1.jpg").write_bytes(b"fake1")
    (dir_b / "photo2.jpg").write_bytes(b"fake2")
    output = tmp_path / "plan.yaml"

    result = runner.invoke(app, [
        "plan",
        "--source", str(dir_a / "**"),
        "--source", str(dir_b / "**"),
        "--output", str(output),
    ])

    assert result.exit_code == 0, result.output
    plan = yaml.safe_load(output.read_text())
    assert _count_files(plan) == 2


def test_plan_detects_duplicates(tmp_path):
    content = b"identical photo content"
    (tmp_path / "photo_a.jpg").write_bytes(content)
    (tmp_path / "photo_b.jpg").write_bytes(content)
    output = tmp_path / "plan.yaml"

    result = runner.invoke(app, [
        "plan",
        "--source", str(tmp_path / "**"),
        "--output", str(output),
    ])

    assert result.exit_code == 0
    plan = yaml.safe_load(output.read_text())
    entries_with_dups = [e for e in _iter_entries(plan) if e["duplicates"]]
    assert len(entries_with_dups) == 1
    assert len(entries_with_dups[0]["duplicates"]) == 1


def test_move_defaults_to_dry_run(tmp_path):
    plan_data = {"sources": [], "files": {}, "archives": []}
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(yaml.dump(plan_data))
    dest = tmp_path / "dest"

    result = runner.invoke(app, ["move", "--plan", str(plan_file), "--dest", str(dest)])

    assert result.exit_code == 0
    assert "dry run" in result.output.lower()
    assert not dest.exists()


def test_move_requires_confirm_for_real_run(tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"fake")
    plan_data = {
        "sources": [],
        "files": {
            "image": {
                "unknown": [{"best": str(img), "dest": "2024/01/01/photo.jpg", "duplicates": []}]
            }
        },
        "archives": [],
    }
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(yaml.dump(plan_data))
    dest = tmp_path / "dest"

    # Without --confirm, should still be dry run
    result = runner.invoke(app, ["move", "--plan", str(plan_file), "--dest", str(dest)])
    assert not (dest / "2024/01/01/photo.jpg").exists()


def test_cleanup_defaults_to_dry_run(tmp_path):
    plan_data = {"sources": [], "files": {}, "archives": []}
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(yaml.dump(plan_data))
    trash = tmp_path / "trash"

    result = runner.invoke(app, ["cleanup", "--plan", str(plan_file), "--trash", str(trash)])

    assert result.exit_code == 0
    assert "dry run" in result.output.lower()
    assert not trash.exists()
