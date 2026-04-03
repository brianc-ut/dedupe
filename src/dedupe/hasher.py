import hashlib
import zipfile
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .models import ScannedFile, DuplicateGroup


def _read_content(scanned_file: ScannedFile) -> bytes:
    """Read file content, handling both regular files and archive members."""
    if not scanned_file.is_archive_member:
        return Path(scanned_file.path).read_bytes()

    if scanned_file.path.startswith("zip://"):
        _, rest = scanned_file.path.split("zip://", 1)
        archive_path, member_name = rest.split("::", 1)
        with zipfile.ZipFile(archive_path, 'r') as zf:
            return zf.read(member_name)

    if scanned_file.path.startswith("tar://"):
        _, rest = scanned_file.path.split("tar://", 1)
        archive_path, member_name = rest.split("::", 1)
        with tarfile.open(archive_path, 'r:*') as tf:
            extracted = tf.extractfile(member_name)
            if extracted is None:
                raise ValueError(f"Cannot extract {member_name} from {archive_path}")
            return extracted.read()

    raise ValueError(f"Unknown archive path format: {scanned_file.path}")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def group_by_hash(
    files: list[ScannedFile],
    progress_callback: Callable[[ScannedFile], None] | None = None,
) -> list[DuplicateGroup]:
    """Group files by content hash. Only hashes files sharing the same size."""
    if not files:
        return []

    # Step 1: group by size
    by_size: dict[int, list[ScannedFile]] = defaultdict(list)
    for f in files:
        by_size[f.size].append(f)

    # Step 2: hash only size-collision candidates
    by_hash: dict[str, list[ScannedFile]] = defaultdict(list)
    for size, size_group in by_size.items():
        if len(size_group) == 1:
            f = size_group[0]
            sentinel = f"unique:{f.path}"
            by_hash[sentinel].append(f)
            if progress_callback:
                progress_callback(f)
        else:
            for f in size_group:
                content = _read_content(f)
                h = _sha256(content)
                by_hash[h].append(f)
                if progress_callback:
                    progress_callback(f)

    return [DuplicateGroup(hash=h, files=group) for h, group in by_hash.items()]
