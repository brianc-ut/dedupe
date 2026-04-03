# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (first time)
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install pytest

# Run all tests
.venv/bin/pytest tests/ -v

# Run a single test file
.venv/bin/pytest tests/test_scanner.py -v

# Run a single test
.venv/bin/pytest tests/test_scanner.py::test_scan_finds_image_files -v

# Run the CLI
.venv/bin/python -m dedupe.cli --help
.venv/bin/dedupe plan --source "/photos/**" --output plan.yaml
.venv/bin/dedupe move --plan plan.yaml --dest /output
.venv/bin/dedupe cleanup --plan plan.yaml --trash /trash
```

## Architecture

Three-mode pipeline: `plan` → `move` → `cleanup`. The YAML plan file is the central artifact — move and cleanup are both "apply the plan" operations and must run after plan.

**Data flow:**
`scanner` collects `ScannedFile` objects → `hasher` groups by size then SHA-256 into `DuplicateGroup` → `selector` picks best copy per group → `metadata` extracts EXIF/video date → `planner` builds and writes YAML plan → `mover` applies it.

**Module responsibilities:**
- `models.py` — shared dataclasses (ScannedFile, ArchiveEntry, DuplicateGroup, SelectedFile, FileMetadata)
- `scanner.py` — glob resolution, file walking, archive inspection (zip/tar in-memory). Returns `(files, archives, warnings)`.
- `hasher.py` — size pre-filter, then SHA-256. Unique-size files get sentinel hash `unique:{path}`. `_read_content()` handles `zip://` and `tar://` archive member paths.
- `selector.py` — picks best copy by earliest mtime, source_index as tiebreaker.
- `metadata.py` — `extract_metadata(path, provider="auto")` for single files; `extract_metadata_batch(paths, provider, max_workers, progress_callback)` for bulk. Python extraction (Pillow/hachoir) runs in parallel via `ThreadPoolExecutor`. Exiftool fallback fires only when Python got no structural metadata: image with no dimensions, or video with no duration AND no date. Batch exiftool runs once for all qualifying files (`_extract_exiftool_batch`). `_needs_exiftool_fallback(result)` encodes the tightened condition.
- `planner.py` — builds plan dict, writes/reads YAML. `files` is a nested dict: `{type: {camera: [entries]}}`. Camera key uses camera name → normalized dimensions (`max(w,h)x min(w,h)`) → `"unknown"`. Entry key is `dest` (not `best_dest`). `hash` omitted when unique; `original_date`/`date_source` omitted when no date found; `duplicates` omitted when empty. Undated files use mtime for `undated/YYYY/MM/DD/` path.
- `mover.py` — `execute_move` and `execute_cleanup`. Both default to `dry_run=True`. Uses `_iter_file_entries()` to traverse the nested `files` dict. Real move ops (`os.rename`/`shutil.move`) are **commented out** in `_safe_move()` — uncomment to enable real moves.
- `cli.py` — Typer entry point. move/cleanup require `--confirm` flag + typing "confirm" at prompt to execute real moves.

**Archive handling:** ZIP and TAR archives are inspected in-memory. Archive members appear as `ScannedFile` with paths like `zip:///path.zip::member/photo.jpg`. The hasher reads their content directly from the archive. Archive members in duplicate lists are skipped by cleanup (can't move loose).

**Safety:** move and cleanup default to dry-run. Real filesystem ops in `mover.py:_safe_move()` are commented out. Uncomment both lines (`os.rename` and `shutil.move`) to enable.
