from dataclasses import dataclass
from datetime import datetime


@dataclass
class ScannedFile:
    path: str           # regular path OR "zip://archive.zip::member" OR "tar://archive.tar::member"
    size: int
    mtime: float
    source_index: int
    is_archive_member: bool
    archive_path: str | None


@dataclass
class ArchiveEntry:
    path: str
    archive_type: str   # "zip", "tar", "unsupported-archive"
    readable: bool
    contained_files: int


@dataclass
class DuplicateGroup:
    hash: str
    files: list[ScannedFile]


@dataclass
class SelectedFile:
    hash: str
    best: ScannedFile
    duplicates: list[ScannedFile]


@dataclass
class FileMetadata:
    original_date: datetime | None
    camera: str | None
    dimensions: str | None      # "WxH" for images
    duration: float | None      # seconds for video
    file_type: str              # "image" or "video"
    date_source: str            # "pillow", "hachoir", "exiftool", "none"
