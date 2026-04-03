# Dedupe Tool — Design Spec

**Date:** 2026-03-26
**Status:** Approved

## Overview

A CLI tool for personal photo/video library management. Scans source directories for duplicate files, produces an editable YAML plan, and applies that plan to consolidate the best copies into a date-organized destination directory. Duplicate extras are moved to a trash folder in a separate cleanup step.

---

## Architecture

Single CLI entry point (`dedupe`) with three subcommands:

```
dedupe plan    --source "<globs>" [--source "<globs>"] --output <plan.yaml> [--metadata-provider auto|python|exiftool]
dedupe move    --plan <plan.yaml> --dest <dir> [--flatten] [--dry-run]
dedupe cleanup --plan <plan.yaml> --trash <dir> [--dry-run]
```

**Flow:**
```
Source globs → scan → size-group → hash candidates → group duplicates → select best → write plan.yaml
                                                                                              ↓
                                                                               dedupe move   (moves best copies to dest)
                                                                               dedupe cleanup (moves extras to trash)
```

**Modules:**
- `scanner.py` — resolves globs, walks directories, collects file paths; inspects archives in-memory
- `hasher.py` — size pre-filter, SHA-256 hashing, groups duplicates
- `selector.py` — picks best copy within each duplicate group
- `metadata.py` — extracts EXIF/video metadata via provider abstraction
- `planner.py` — builds and writes YAML plan
- `mover.py` — reads plan, executes move operations (stubbed initially)
- `cli.py` — Typer entry point wiring all subcommands

---

## Scanning & File Support

**Supported extensions (defaults):**
- Images: `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, `.tiff`, `.raw`, `.cr2`, `.arw`, `.dng`
- Video: `.mov`, `.mp4`, `.mpeg`, `.mpg`, `.avi`, `.m4v`
- Archives (inspected): `.zip`, `.tar`, `.tar.gz`, `.tgz`
- Archives (unsupported): `.7z`, `.rar` — flagged as `type: unsupported-archive` in plan, not inspected

**Source input:** comma-separated recursive globs per `--source` flag, multiple flags allowed.
Example: `--source "/photos/2023/**,/Volumes/External/**/DCIM"`

**Scanning rules:**
- Symlinks: not followed (avoid infinite loops)
- Hidden directories (`.` prefix): skipped by default; `--include-hidden` to override
- Unreadable files: skipped with warning

**Deduplication algorithm:**
1. Group all files by size — files with a unique size cannot be duplicates
2. Hash only files in size-collision groups (SHA-256 on full content)
3. Files sharing a hash are duplicates

---

## Archive Handling

Archives are inspected in-memory (never extracted to disk). Contained image/video files are hashed and participate in duplicate detection normally alongside loose files.

**Plan output for archives:**
- Each contained file is tracked with its source noted as `zip://path/to/archive.zip::internal/path.jpg`
- If a zip's contents are fully accounted for by loose files already in the scan, the plan flags the zip as `archive_status: fully_covered`
- If partially covered: `archive_status: partially_covered` with a list of uncovered files
- If no overlap: `archive_status: no_overlap`

This gives visibility to decide whether to extend the tool or handle the archive manually. No automatic extraction or deletion of archives.

**Supported archive libs:** `zipfile` and `tarfile` (both stdlib — no new dependency).

---

## Best Copy Selection

All files in a duplicate group are byte-for-byte identical. Selection only determines which path becomes the canonical copy:

1. **Earliest `mtime`** — primary criterion (most likely the original)
2. **Source order** — tiebreaker (earlier `--source` arguments are preferred)

Since all copies are identical, no data is ever lost regardless of which is chosen. Extras go to trash, not permanent deletion.

---

## Metadata Extraction

**Provider abstraction** (`--metadata-provider`):

- `auto` (default): try pure Python first; fall back to exiftool silently if installed and pure Python returned no date
- `python`: Pillow (images) + hachoir (video) only
- `exiftool`: exiftool only (must be installed via `brew install exiftool`)

**Fields extracted:** `original_date`, `camera` (images only), `dimensions` (images only), `duration` (video only), `date_source` (records which provider succeeded).

If metadata extraction fails entirely: `original_date: null`, `date_source: none`.

---

## Plan File Format

```yaml
# dedupe plan - generated 2026-03-26T10:22:01
sources:
  - /photos/2023/**
  - /Volumes/External/**/DCIM

files:
  - hash: a3f9c2b1d4e8f...
    best: /photos/2023/IMG_1234.jpg
    best_dest: 2024/03/15/IMG_1234.jpg    # relative to --dest
    meta:
      original_date: "2024-03-15T10:22:01"
      camera: "Apple iPhone 13"
      dimensions: "4032x3024"
      type: image
      date_source: pillow
    duplicates:
      - /Volumes/External/DCIM/IMG_1234.jpg
      - zip://path/to/backup.zip::DCIM/IMG_1234.jpg

  - hash: unique
    best: /photos/2023/IMG_5678.jpg
    best_dest: 2024/06/22/IMG_5678.jpg
    meta:
      original_date: "2024-06-22T14:05:33"
      type: image
      date_source: pillow
    duplicates: []

archives:
  - path: /photos/backup.zip
    archive_status: fully_covered
    type: zip
    contained_files: 42
    uncovered_files: []

  - path: /photos/misc.rar
    type: unsupported-archive
```

**Notes:**
- `best_dest` is relative — `move` resolves against `--dest`
- User can edit `best` to promote a different copy or edit `best_dest` to change output path
- `duplicates: []` means unique file — still moved by move mode, nothing for cleanup
- Files with no extractable date go to `undated/filename`

---

## Destination Structure

Default: `YYYY/MM/DD/filename` based on `original_date` (EXIF) or `mtime` fallback.
`--flatten`: all files placed directly in `--dest` with no subdirectories.
Filename collisions: append `_1`, `_2`, etc.

---

## Move & Cleanup Behavior

**Safety:**
- Both `move` and `cleanup` **default to dry-run** — they print what would happen without touching the filesystem
- To execute for real, pass `--confirm` flag OR omit it and respond to an interactive prompt requiring the user to type `confirm`
- Filesystem-mutating calls are also **commented out in the initial implementation** as an additional safeguard

**Move semantics:**
- `os.rename()` for same-filesystem moves (atomic)
- `shutil.move()` fallback for cross-filesystem moves
- On failure, source file remains in place — no partial state
- File is never duplicated: original is gone only after dest is confirmed written

**Move mode:** moves `best` → resolved `best_dest` for every entry in plan.
**Cleanup mode:** moves all `duplicates` entries → `--trash` directory. Archive files listed as duplicates (zip-contained) are noted in output but not moved (they exist inside an archive, not as loose files).

---

## Error Handling

- Unreadable file during scan: skip with warning
- Glob resolves to no files: warn, continue
- Plan references missing file: skip with warning
- Archive inspection failure: flag archive as `archive_status: unreadable`, continue
- All warnings/errors collected and printed as summary at end of each run
- Non-zero exit code if any errors occurred (warnings alone do not fail)

---

## Dependencies

```
typer
rich
pillow
hachoir
pyyaml
```

`exiftool` (optional system dependency, `brew install exiftool`) used only when `--metadata-provider exiftool` or as auto-fallback.

`zipfile` and `tarfile` are Python stdlib — no additional dependency for archive support.

---

## Future Considerations

- Perceptual hashing (e.g., `imagehash`) for near-duplicate / same-photo-different-format detection — designed to slot in alongside exact hash grouping
- Amazon Photos integration for pulling source files
- Automatic archive extraction / cleanup based on `archive_status`
