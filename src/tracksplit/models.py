"""Data models for TrackSplit."""
from dataclasses import dataclass, field


@dataclass
class Chapter:
    """A chapter marker from a video file."""
    index: int
    title: str
    start: float  # seconds
    end: float  # seconds
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class TrackMeta:
    """Metadata for a single output track."""
    number: int
    title: str
    start: float
    end: float
    artist: str = ""  # per-track artist parsed from chapter title
    publisher: str = ""
    genre: list[str] = field(default_factory=list)
    artists: list[str] = field(default_factory=list)
    artist_mbids: list[str] = field(default_factory=list)


@dataclass
class AlbumMeta:
    """Metadata for the output album."""
    artist: str
    album: str
    date: str = ""
    genre: list[str] = field(default_factory=list)
    festival: str = ""
    stage: str = ""
    venue: str = ""
    comment: str = ""
    musicbrainz_artistid: str = ""
    tracks: list[TrackMeta] = field(default_factory=list)
    cover_data: bytes | None = None
    albumartists: list[str] = field(default_factory=list)
    albumartist_mbids: list[str] = field(default_factory=list)

    @property
    def artist_folder(self) -> str:
        return self.artist or "Unknown Artist"

    @property
    def album_folder(self) -> str:
        return self.album or "Unknown Album"
