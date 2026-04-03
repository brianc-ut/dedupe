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
- `metadata.py` — `extract_metadata(path, provider="auto")`. Pillow for images, hachoir for video. Auto-fallback to exiftool if available and no date found.
- `planner.py` — builds plan dict, writes/reads YAML. Sentinel hash `unique:{path}` is written as `"unique"` in output. `files` in the plan is a nested dict: `{type: {camera: [entries]}}`. Each entry has flattened metadata fields (`original_date`, `date_source`, etc.) — no `meta` sub-dict.
- `mover.py` — `execute_move` and `execute_cleanup`. Both default to `dry_run=True`. Uses `_iter_file_entries()` to traverse the nested `files` dict. Real move ops (`os.rename`/`shutil.move`) are **commented out** in `_safe_move()` — uncomment to enable real moves.
- `cli.py` — Typer entry point. move/cleanup require `--confirm` flag + typing "confirm" at prompt to execute real moves.

**Archive handling:** ZIP and TAR archives are inspected in-memory. Archive members appear as `ScannedFile` with paths like `zip:///path.zip::member/photo.jpg`. The hasher reads their content directly from the archive. Archive members in duplicate lists are skipped by cleanup (can't move loose).

**Safety:** move and cleanup default to dry-run. Real filesystem ops in `mover.py:_safe_move()` are commented out. Uncomment both lines (`os.rename` and `shutil.move`) to enable.
