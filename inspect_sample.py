import argparse
from pathlib import Path

import cv2
import numpy as np


OUTPUT = Path("analysis_frames")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract representative frames from an MP4 video.")
    parser.add_argument("video", type=Path, help="MP4 video to inspect")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="Directory for extracted frames")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / fps
    print(f"size={width}x{height} fps={fps:.3f} frames={frame_count} duration={duration:.3f}s")

    times = np.linspace(0.05 * duration, 0.95 * duration, 9)
    thumbs = []
    for index, seconds in enumerate(times):
        capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
        ok, frame = capture.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        path = args.output / f"frame_{index:02d}_{seconds:06.2f}s.jpg"
        cv2.imwrite(str(path), frame)
        thumb = cv2.resize(frame, (216, 384), interpolation=cv2.INTER_AREA)
        cv2.putText(thumb, f"{seconds:.1f}s sharp={sharpness:.0f}", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 0), 1, cv2.LINE_AA)
        thumbs.append(thumb)
        print(f"sample={seconds:.3f}s sharpness={sharpness:.2f} file={path}")

    if thumbs:
        rows = []
        for start in range(0, len(thumbs), 3):
            row = thumbs[start : start + 3]
            while len(row) < 3:
                row.append(np.zeros_like(thumbs[0]))
            rows.append(cv2.hconcat(row))
        cv2.imwrite(str(args.output / "contact_sheet.jpg"), cv2.vconcat(rows))


if __name__ == "__main__":
    main()
