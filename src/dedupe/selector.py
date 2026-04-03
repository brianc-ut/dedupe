from .models import DuplicateGroup, SelectedFile


def select_best(group: DuplicateGroup) -> SelectedFile:
    """
    Select the best copy from a duplicate group.
    Criteria: loose files beat archive members; then earliest mtime; source_index as tiebreaker.
    canonical_mtime is the minimum mtime across all copies (including archive members).
    """
    sorted_files = sorted(group.files, key=lambda f: (not f.is_dest_file, f.is_archive_member, f.mtime, f.source_index))
    best = sorted_files[0]
    duplicates = sorted_files[1:]
    canonical_mtime = min(f.mtime for f in group.files)
    return SelectedFile(
        hash=group.hash,
        best=best,
        duplicates=duplicates,
        canonical_mtime=canonical_mtime,
    )
