from datetime import datetime
from pathlib import Path

import yaml

from .models import ArchiveEntry, FileMetadata, ScannedFile, SelectedFile


def compute_dest_path(
    scanned_file: ScannedFile,
    metadata: FileMetadata,
    flatten: bool = False,
    existing_dests: set[str] | None = None,
    canonical_mtime: float | None = None,
) -> str:
    """Compute the relative destination path for the best copy of a file."""
    # Extract filename from archive member paths like zip://archive.zip::dir/photo.jpg
    raw_path = scanned_file.path.split("::")[-1] if "::" in scanned_file.path else scanned_file.path
    filename = Path(raw_path).name

    if flatten:
        base = filename
    elif metadata.original_date:
        d = metadata.original_date
        base = f"{d.year:04d}/{d.month:02d}/{d.day:02d}/{filename}"
    else:
        mtime = canonical_mtime if canonical_mtime is not None else scanned_file.mtime
        d = datetime.fromtimestamp(mtime)
        base = f"undated/{d.year:04d}/{d.month:02d}/{d.day:02d}/{filename}"

    if existing_dests is None or base not in existing_dests:
        return base

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    dir_prefix = base[: base.rfind(filename)]
    for i in range(1, 10000):
        candidate = f"{dir_prefix}{stem}_{i}{suffix}"
        if candidate not in existing_dests:
            return candidate

    raise ValueError(f"Too many filename collisions for {filename}")


def _archive_status(
    archive_path: str,
    selected: list[SelectedFile],
) -> tuple[str, list[str]]:
    """Determine archive coverage status based on selected file groups."""
    contained_paths = set()
    covered_paths = set()

    for entry in selected:
        for f in [entry.best, *entry.duplicates]:
            if f.is_archive_member and f.archive_path == archive_path:
                contained_paths.add(f.path)
                all_in_group = [entry.best, *entry.duplicates]
                has_loose = any(not x.is_archive_member for x in all_in_group)
                if has_loose:
                    covered_paths.add(f.path)

    if not contained_paths:
        return "no_overlap", []

    uncovered = [p for p in contained_paths if p not in covered_paths]
    if not uncovered:
        return "fully_covered", []
    if covered_paths:
        return "partially_covered", uncovered
    return "no_overlap", uncovered


def build_plan(
    sources: list[str],
    selected: list[SelectedFile],
    metadata: dict[str, FileMetadata],
    archives: list[ArchiveEntry],
    flatten: bool = False,
    dest_dir: str | None = None,
) -> dict:
    """Build the plan dict from selected files and metadata."""
    existing_dests: set[str] = set()
    files_by_type_camera: dict = {}

    for sel in selected:
        best_path = sel.best.path
        # Duplicates from the dest directory are already in place — exclude from cleanup list
        source_duplicates = [d for d in sel.duplicates if not d.is_dest_file]

        meta = metadata.get(best_path, FileMetadata(
            original_date=None, camera=None, dimensions=None,
            duration=None, file_type="image", date_source="none"
        ))

        is_unique = sel.hash.startswith("unique:")
        file_type = meta.file_type

        # Camera grouping: use camera name, or normalized dimensions, or "unknown"
        if meta.camera:
            camera = meta.camera
        elif meta.dimensions:
            w, h = (int(x) for x in meta.dimensions.split("x"))
            camera = f"{max(w, h)}x{min(w, h)}"
        else:
            camera = "unknown"

        if sel.best.is_dest_file and dest_dir:
            # File is already at the destination — record its relative path, no move needed
            best_dest = str(Path(best_path).relative_to(dest_dir))
            existing_dests.add(best_dest)
            entry: dict = {"best": best_path, "dest": best_dest, "already_at_dest": True}
            if not is_unique:
                entry["hash"] = sel.hash
            if meta.original_date:
                entry["original_date"] = meta.original_date.isoformat()
            if meta.date_source != "none":
                entry["date_source"] = meta.date_source
            if meta.dimensions:
                entry["dimensions"] = meta.dimensions
            if meta.duration is not None:
                entry["duration"] = meta.duration
            if source_duplicates:
                entry["duplicates"] = [d.path for d in source_duplicates]
        else:
            # canonical_mtime: use if earlier than best's own mtime
            canonical_mtime = sel.canonical_mtime
            if canonical_mtime is not None and canonical_mtime >= sel.best.mtime:
                canonical_mtime = None  # best already has the earliest mtime

            best_dest = compute_dest_path(sel.best, meta, flatten=flatten,
                                          existing_dests=existing_dests,
                                          canonical_mtime=canonical_mtime)
            existing_dests.add(best_dest)

            entry = {"best": best_path, "dest": best_dest}
            if not is_unique:
                entry["hash"] = sel.hash
            if canonical_mtime is not None:
                entry["canonical_mtime"] = canonical_mtime
            if meta.original_date:
                entry["original_date"] = meta.original_date.isoformat()
            if meta.date_source != "none":
                entry["date_source"] = meta.date_source
            if meta.dimensions:
                entry["dimensions"] = meta.dimensions
            if meta.duration is not None:
                entry["duration"] = meta.duration
            if source_duplicates:
                entry["duplicates"] = [d.path for d in source_duplicates]

        files_by_type_camera.setdefault(file_type, {}).setdefault(camera, []).append(entry)

    archive_entries = []
    for arc in archives:
        entry: dict = {"path": arc.path, "type": arc.archive_type}
        if arc.archive_type == "unsupported-archive":
            archive_entries.append(entry)
            continue
        if not arc.readable:
            entry["archive_status"] = "unreadable"
            archive_entries.append(entry)
            continue

        status, uncovered = _archive_status(arc.path, selected)
        entry["archive_status"] = status
        entry["contained_files"] = arc.contained_files
        entry["uncovered_files"] = uncovered
        archive_entries.append(entry)

    return {
        "sources": sources,
        "files": files_by_type_camera,
        "archives": archive_entries,
    }


def write_plan(plan: dict, output_path: str) -> None:
    """Write plan dict to a YAML file."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(f"# dedupe plan - generated {datetime.now().isoformat(timespec='seconds')}\n")
        yaml.dump(plan, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def read_plan(plan_path: str) -> dict:
    """Read a YAML plan file."""
    with open(plan_path, 'r') as f:
        return yaml.safe_load(f)
