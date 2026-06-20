from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float


@dataclass(frozen=True)
class SelectedFrame:
    index: int
    timestamp_seconds: float
    sharpness: float
    image: object


@dataclass(frozen=True)
class OCRToken:
    text: str
    confidence: float
    left: float
    top: float
    right: float
    bottom: float

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class Observation:
    name: str
    points: int | None
    rank: int | None
    raw_name: str
    raw_points: str
    raw_rank: str
    confidence: float
    timestamp_seconds: float
    frame_index: int
    source_frame: str
    issues: list[str] = field(default_factory=list)


@dataclass
class MemberResult:
    name: str
    points: int | None
    rank: int | None
    raw_name: str
    raw_points: str
    raw_rank: str
    confidence: float
    review: bool
    issues: list[str]
    timestamps: list[float]
    source_frames: list[str]
    observation_count: int

    def to_dict(self) -> dict:
        data = asdict(self)
        data["issues"] = "; ".join(self.issues)
        data["timestamps"] = "; ".join(f"{value:.3f}" for value in self.timestamps)
        data["source_frames"] = "; ".join(self.source_frames)
        return data

