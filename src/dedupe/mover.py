import os
import shutil
from pathlib import Path


def _is_archive_member(path: str) -> bool:
    return path.startswith("zip://") or path.startswith("tar://")


def _safe_move(src: str, dst: str) -> None:
    """
    Move src to dst atomically where possible.
    Uses os.rename (same filesystem, atomic) with shutil.move fallback.
    NOTE: Real filesystem operations are commented out — remove comments to enable.
    """
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    try:
        # os.rename(src, dst)  # STUBBED — uncomment to enable real moves
        pass
    except OSError:
        # shutil.move(src, dst)  # STUBBED — uncomment to enable real moves
        pass


def execute_move(
    plan: dict,
    dest: str,
    dry_run: bool = True,
    flatten: bool = False,
) -> dict:
    """
    Execute move mode: move best copies to dest directory.
    Defaults to dry_run=True. Pass dry_run=False with explicit --confirm to move for real.
    """
    planned = []
    warnings = []

    for entry in plan.get("files", []):
        src = entry["best"]
        if not Path(src).exists():
            warnings.append(f"Warning: source file not found, skipping: {src}")
            continue
        dst = str(Path(dest) / entry["best_dest"])
        planned.append({"from": src, "to": dst})
        if not dry_run:
            _safe_move(src, dst)

    return {"dry_run": dry_run, "planned": planned, "warnings": warnings}


def execute_cleanup(
    plan: dict,
    trash: str,
    dry_run: bool = True,
) -> dict:
    """
    Execute cleanup mode: move duplicate extras to trash directory.
    Defaults to dry_run=True. Pass dry_run=False with explicit --confirm to move for real.
    """
    planned = []
    warnings = []
    skipped_archive_members = []

    for entry in plan.get("files", []):
        for dup_path in entry.get("duplicates", []):
            if _is_archive_member(dup_path):
                skipped_archive_members.append(dup_path)
                continue
            if not Path(dup_path).exists():
                warnings.append(f"Warning: duplicate not found, skipping: {dup_path}")
                continue
            filename = Path(dup_path).name
            dst = str(Path(trash) / filename)
            # Handle collisions in trash
            if Path(dst).exists():
                stem = Path(filename).stem
                suffix = Path(filename).suffix
                for i in range(1, 10000):
                    candidate = str(Path(trash) / f"{stem}_{i}{suffix}")
                    if not Path(candidate).exists():
                        dst = candidate
                        break
            planned.append({"from": dup_path, "to": dst})
            if not dry_run:
                _safe_move(dup_path, dst)

    return {
        "dry_run": dry_run,
        "planned": planned,
        "warnings": warnings,
        "skipped_archive_members": skipped_archive_members,
    }
