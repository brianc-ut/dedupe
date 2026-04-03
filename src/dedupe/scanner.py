# src/dedupe/scanner.py
import glob as glob_module
import zipfile
import tarfile
from datetime import datetime
from pathlib import Path

from .models import ScannedFile, ArchiveEntry

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.raw', '.cr2', '.arw', '.dng'}
VIDEO_EXTENSIONS = {'.mov', '.mp4', '.mpeg', '.mpg', '.avi', '.m4v'}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
INSPECTED_ARCHIVE_EXTENSIONS = {'.zip', '.tar', '.tgz'}
UNSUPPORTED_ARCHIVE_EXTENSIONS = {'.7z', '.rar'}


def _resolve_globs(source: str, include_hidden: bool = False) -> list[str]:
    """Expand comma-separated glob patterns into a deduplicated list of paths."""
    patterns = [p.strip() for p in source.split(',')]
    paths: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in glob_module.glob(pattern, recursive=True, include_hidden=include_hidden):
            resolved = str(Path(match).resolve())
            if resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
    return paths


def scan_sources(
    sources: list[str],
    include_hidden: bool = False,
) -> tuple[list[ScannedFile], list[ArchiveEntry], list[str]]:
    """Scan source glob patterns. Returns (files, archives, warnings)."""
    seen_paths: set[str] = set()
    files: list[ScannedFile] = []
    archives: list[ArchiveEntry] = []
    warnings: list[str] = []

    for source_index, source in enumerate(sources):
        paths = _resolve_globs(source, include_hidden=include_hidden)
        if not paths:
            warnings.append(f"Warning: glob '{source}' matched no files")
            continue

        for abs_path in paths:
            if abs_path in seen_paths:
                continue

            p = Path(abs_path)
            if not p.is_file():
                continue

            if not include_hidden and any(part.startswith('.') for part in p.parts):
                continue

            ext = p.suffix.lower()
            # Handle .tar.gz specially
            is_tar_gz = abs_path.endswith('.tar.gz')

            if ext in SUPPORTED_EXTENSIONS:
                try:
                    stat = p.stat()
                    files.append(ScannedFile(
                        path=abs_path,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        source_index=source_index,
                        is_archive_member=False,
                        archive_path=None,
                    ))
                    seen_paths.add(abs_path)
                except OSError as e:
                    warnings.append(f"Warning: cannot read {abs_path}: {e}")

            elif ext in INSPECTED_ARCHIVE_EXTENSIONS or is_tar_gz:
                archive_files, archive_entry, archive_warnings = _inspect_archive(
                    abs_path, source_index
                )
                files.extend(archive_files)
                for af in archive_files:
                    seen_paths.add(af.path)
                archives.append(archive_entry)
                warnings.extend(archive_warnings)
                seen_paths.add(abs_path)

            elif ext in UNSUPPORTED_ARCHIVE_EXTENSIONS:
                archives.append(ArchiveEntry(
                    path=abs_path,
                    archive_type="unsupported-archive",
                    readable=False,
                    contained_files=0,
                ))
                seen_paths.add(abs_path)

    return files, archives, warnings


def scan_dest(dest_dir: str) -> list[ScannedFile]:
    """Scan existing media files in dest directory. Returns ScannedFile with is_dest_file=True."""
    result = []
    dest_path = Path(dest_dir)
    if not dest_path.is_dir():
        return result
    for p in dest_path.rglob('*'):
        if not p.is_file():
            continue
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            stat = p.stat()
            result.append(ScannedFile(
                path=str(p),
                size=stat.st_size,
                mtime=stat.st_mtime,
                source_index=-1,
                is_archive_member=False,
                archive_path=None,
                is_dest_file=True,
            ))
        except OSError:
            pass
    return result


def _inspect_archive(
    archive_path: str,
    source_index: int,
) -> tuple[list[ScannedFile], ArchiveEntry, list[str]]:
    """Inspect a zip or tar archive in-memory, returning member ScannedFiles."""
    p = Path(archive_path)
    warnings: list[str] = []
    member_files: list[ScannedFile] = []

    try:
        is_zip = p.suffix.lower() == '.zip'
        if is_zip:
            with zipfile.ZipFile(archive_path, 'r') as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    if Path(info.filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue
                    if any(info.date_time):
                        mtime = datetime(*info.date_time).timestamp()
                    else:
                        mtime = p.stat().st_mtime
                    member_files.append(ScannedFile(
                        path=f"zip://{archive_path}::{info.filename}",
                        size=info.file_size,
                        mtime=mtime,
                        source_index=source_index,
                        is_archive_member=True,
                        archive_path=archive_path,
                    ))
        else:
            with tarfile.open(archive_path, 'r:*') as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    if Path(member.name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue
                    member_files.append(ScannedFile(
                        path=f"tar://{archive_path}::{member.name}",
                        size=member.size,
                        mtime=float(member.mtime),
                        source_index=source_index,
                        is_archive_member=True,
                        archive_path=archive_path,
                    ))

        return member_files, ArchiveEntry(
            path=archive_path,
            archive_type="zip" if is_zip else "tar",
            readable=True,
            contained_files=len(member_files),
        ), warnings

    except Exception as e:
        warnings.append(f"Warning: cannot inspect archive {archive_path}: {e}")
        return [], ArchiveEntry(
            path=archive_path,
            archive_type=p.suffix.lower().lstrip('.'),
            readable=False,
            contained_files=0,
        ), warnings
