# dedupe

A photo and video deduplication tool. Scans one or more source directories for duplicate media files, selects the best copy of each, and produces a YAML plan describing what to move and what to discard. The plan is then applied in two separate steps: moving the best copies to an organized destination, and relocating duplicates to a trash directory.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Optional: install `exiftool` system-wide for extended metadata extraction fallback.

## Workflow

The pipeline has three stages, each a separate subcommand:

```
plan → move → cleanup
```

The YAML plan file is the central artifact. `move` and `cleanup` both read it — they cannot run without a plan.

### 1. Plan

Scan sources, detect duplicates, and write a YAML plan:

```bash
dedupe plan --source "/photos/**" --source "/backup/photos/**" --output plan.yaml
```

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `--source` | Yes (repeatable) | Glob pattern(s) to scan. Pass multiple times for multiple sources. Each value may also be a comma-separated list of globs. |
| `--output` | Yes | Path to write the YAML plan file. |
| `--metadata-provider` | No | Metadata extraction backend: `auto` (default), `pillow`, `hachoir`, or `exiftool`. `auto` tries Pillow then hachoir, then falls back to exiftool if available and no date was found. |
| `--include-hidden` | No | Include hidden files and directories (those starting with `.`). Default: excluded. |

Exits with code 1 if any warnings were produced (e.g., a glob matched nothing, an archive could not be read).

### 2. Move

Copy the best version of each file to a destination directory:

```bash
dedupe move --plan plan.yaml --dest /organized
```

By default this is a **dry run** — no files are touched. Pass `--confirm` and type `confirm` at the prompt to execute real moves.

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `--plan` | Yes | Path to the plan YAML produced by `plan`. |
| `--dest` | Yes | Destination root directory. Files are placed under date-based subdirectories (`YYYY/MM/DD/filename`) unless `--flatten` is set. |
| `--flatten` | No | Write all files directly into `--dest` with no subdirectory structure. |
| `--confirm` | No | Prompt for confirmation before executing real filesystem moves. Without this flag the command always dry-runs. |

Exits with code 1 if any warnings were produced.

### 3. Cleanup

Move duplicate extras to a trash directory:

```bash
dedupe cleanup --plan plan.yaml --trash /trash
```

Like `move`, this is a **dry run** by default. Pass `--confirm` and type `confirm` to execute real moves.

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `--plan` | Yes | Path to the plan YAML produced by `plan`. |
| `--trash` | Yes | Directory to receive duplicate files. |
| `--confirm` | No | Prompt for confirmation before executing real filesystem moves. Without this flag the command always dry-runs. |

Archive members (files inside ZIP or TAR archives) are listed but skipped during cleanup — they cannot be extracted and moved as loose files by this tool.

Exits with code 1 if any warnings were produced.

## Theory of Operation

### Scanning

`dedupe plan` accepts one or more `--source` glob patterns. Each pattern is expanded (including `**` recursive wildcards) into a list of absolute file paths. Sources are assigned an index in the order they are provided — this index is used as a tiebreaker during duplicate selection, biasing toward files from earlier-listed sources.

Supported media types:

- **Images:** `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, `.tiff`, `.raw`, `.cr2`, `.arw`, `.dng`
- **Video:** `.mov`, `.mp4`, `.mpeg`, `.mpg`, `.avi`, `.m4v`

ZIP and TAR archives (`.zip`, `.tar`, `.tgz`, `.tar.gz`) are inspected in-memory. Media files found inside them participate in deduplication just like loose files. Their paths appear internally as `zip:///path/to/archive.zip::member/photo.jpg`. Archives in `.7z` or `.rar` format are noted but not inspected.

### Deduplication

Files are grouped into duplicate sets using a two-phase hash:

1. **Size pre-filter:** Files with a unique size cannot be duplicates and are immediately assigned a sentinel hash without reading their content.
2. **SHA-256:** Files sharing a size are fully hashed. Files with matching SHA-256 hashes are considered identical regardless of filename, location, or modification time.

### Selection

Within each duplicate group, the **best copy** is chosen by:

1. Earliest modification time (`mtime`)
2. Lower source index as a tiebreaker (earlier `--source` argument wins)

All other copies in the group become duplicates.

### Metadata extraction

EXIF and video metadata is extracted from the best copy of each group:

- **Images:** Pillow reads standard EXIF tags (DateTimeOriginal, DateTime, GPS).
- **Video:** hachoir parses container metadata for creation timestamps.
- **Fallback:** If no date is found and `exiftool` is installed, it is tried automatically (when `--metadata-provider auto`).

The extracted date drives the destination path under `move`: files are placed at `YYYY/MM/DD/filename.ext`. Files with no extractable date fall back to the file's modification timestamp and are placed at `undated/YYYY/MM/DD/filename.ext`. Use `--flatten` to skip all subdirectory organization.

### The plan file

The YAML plan is a human-readable record of every decision. Files are grouped first by media type (`image`, `video`), then by camera model (`unknown` when no camera metadata is available):

```yaml
sources:
  - /photos/**
files:
  image:
    Apple iPhone 14 Pro:
      - hash: a3f9...
        best: /photos/vacation/img_001.jpg
        best_dest: 2023/07/04/img_001.jpg
        original_date: '2023-07-04T14:22:00'
        date_source: exif
        duplicates:
          - /backup/photos/img_001.jpg
    unknown:
      - hash: unique
        best: /photos/misc/scan.jpg
        best_dest: undated/2015/03/22/scan.jpg
  video:
    unknown:
      - hash: b8c2...
        best: /photos/clip.mp4
        best_dest: 2023/07/05/clip.mp4
        original_date: '2023-07-05T09:15:00'
        date_source: hachoir
archives:
  - path: /photos/old_backup.zip
    type: zip
    archive_status: fully_covered
    contained_files: 12
    uncovered_files: []
```

Fields are omitted when not applicable:
- `original_date` and `date_source` are absent when no date metadata was found
- `duplicates` is absent when the file has no duplicates
- Undated files are placed under `undated/YYYY/MM/DD/` using the file's modification timestamp

`archive_status` values:
- `fully_covered` — every media file in the archive has a loose duplicate; the archive is safe to delete manually.
- `partially_covered` — some archive members have loose duplicates, some do not.
- `no_overlap` — no archive members match any loose file.
- `unreadable` — the archive could not be opened.

### Safety

- `move` and `cleanup` are **dry-run by default**. No files are moved without `--confirm` and an explicit `confirm` prompt response.
- The underlying filesystem move operations in `mover.py` (`os.rename` / `shutil.move`) are commented out in the source. To enable real moves, uncomment those lines.
- No files are ever deleted — duplicates are relocated to a trash directory, not removed.
