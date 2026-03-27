from .models import DuplicateGroup, SelectedFile


def select_best(group: DuplicateGroup) -> SelectedFile:
    """
    Select the best copy from a duplicate group.
    Criteria: earliest mtime first; source_index as tiebreaker.
    """
    sorted_files = sorted(group.files, key=lambda f: (f.mtime, f.source_index))
    best = sorted_files[0]
    duplicates = sorted_files[1:]
    return SelectedFile(hash=group.hash, best=best, duplicates=duplicates)
