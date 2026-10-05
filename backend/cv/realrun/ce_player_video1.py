#!/usr/bin/env python3
"""Reproducible CE_Player validation for Susana's 12-frame video1 sequence.

Credits CE_Player (https://github.com/mecanosaurio/CE_Player, 2017):
Stage 1 uses its Lucas-Kanade parameters verbatim (goodFeaturesToTrack
qualityLevel=0.01, minDistance=4, 10px grid thinning, calcOpticalFlowPyrLK
winSize=(15,15), maxLevel=2, criteria=(EPS|COUNT,10,0.01), 0.5px
forward-backward rejection). Stage 2 mirrors its frame-difference blob
tracking (absdiff, Gaussian blur 5x5, Otsu threshold, 3x3 open, largest
contour centroid assigned to frame i+1).

Validated against Susana's TLD centers in data.npz (12x2 float64).
Velocity follows her notebook expression:
    v_um_min = disp_px_40pct * 100000 / (2 * 1400 * 40)
where the divisor 2 is the two-minute frame interval (Informe 1 verbatim:
"the time step ... corresponds to 2 minutes").

Intentionally standalone (no cv/pipeline imports): the Google Drive frames
are not present in CI test jobs, so this real-data runner must stay
rerunnable anywhere the files exist. Dependencies: opencv-python or
opencv-python-headless, plus numpy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

EXPECTED = [f"image{i:04d}.jpg" for i in range(9, 21)]
SRC_W, SRC_H = 3280, 2464
RESIZED_W, RESIZED_H = 1312, 986
NPZ_BYTES = 456
SCALE = 0.4
GRID = 10
FB_MAX = 0.5
FACTOR = 100000.0 / (2.0 * 1400.0 * 40.0)
HERS_MEAN = 74.1
HERS_STD = 12.2


class ContractError(RuntimeError):
    """Raised when real-run inputs violate the documented contract."""


def log(message: str) -> None:
    print(message, flush=True)


def load_frames(frames_dir: Path):
    paths = sorted(frames_dir.glob("*.jpg"))
    names = [p.name for p in paths]
    log(f"EVIDENCE frame_order={names}")
    if names != EXPECTED:
        raise ContractError(f"frame names/order {names} != {EXPECTED}")
    images = []
    for path in paths:
        size = path.stat().st_size
        if not 3_000_000 <= size <= 5_500_000:
            raise ContractError(f"{path.name} bytes {size} outside [3000000, 5500000]")
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ContractError(f"cv2 failed to decode {path.name}")
        height, width = image.shape[:2]
        if (width, height) != (SRC_W, SRC_H):
            raise ContractError(f"{path.name} dims {(width, height)} != {(SRC_W, SRC_H)}")
        log(f"EVIDENCE frame={path.name} bytes={size} dims={width}x{height}")
        images.append(image)
    return paths, images


def load_npz(npz_path: Path) -> np.ndarray:
    size = npz_path.stat().st_size
    log(f"EVIDENCE npz_bytes={size}")
    if size != NPZ_BYTES:
        raise ContractError(f"npz bytes {size} != {NPZ_BYTES}")
    with np.load(npz_path, allow_pickle=False) as archive:
        log(f"EVIDENCE npz_keys={list(archive.files)}")
        arrays = {key: np.asarray(archive[key]) for key in archive.files}
    for key, value in arrays.items():
        log(
            f"EVIDENCE npz_key={key} shape={value.shape} dtype={value.dtype} "
            f"min={float(value.min()) if value.size else None} "
            f"max={float(value.max()) if value.size else None}"
        )
    candidates = [
        value.astype(np.float64)
        for value in arrays.values()
        if value.shape == (12, 2)
    ]
    if len(candidates) != 1:
        raise ContractError(
            f"expected exactly one (12, 2) TLD array, found {len(candidates)}; "
            f"keys={list(arrays)}"
        )
    centers = candidates[0]
    if not np.all(np.isfinite(centers)):
        raise ContractError("TLD centers contain NaN or infinity")
    log(
        f"EVIDENCE tld_range x=[{centers[:, 0].min():.6f}, {centers[:, 0].max():.6f}] "
        f"y=[{centers[:, 1].min():.6f}, {centers[:, 1].max():.6f}]"
    )
    return centers


def pick_space(centers: np.ndarray):
    x_max = float(centers[:, 0].max())
    y_max = float(centers[:, 1].max())
    if x_max < 1400.0 and y_max < 1000.0:
        return "40pct", 1.0
    if x_max <= SRC_W and y_max <= SRC_H:
        return "original", SCALE
    raise ContractError(f"TLD maxima x={x_max} y={y_max} fit neither space")


def to_gray(images, space: str):
    grays = []
    for index, image in enumerate(images):
        working = (
            cv2.resize(image, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
            if space == "40pct"
            else image
        )
        gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
        if space == "40pct" and gray.shape[::-1] != (RESIZED_W, RESIZED_H):
            raise ContractError(
                f"resized frame {index} is {gray.shape[::-1]}, expected {(RESIZED_W, RESIZED_H)}"
            )
        grays.append(gray)
    log(
        f"EVIDENCE processing_space={space} dims={grays[0].shape[::-1]} "
        f"count={len(grays)}"
    )
    return grays


def thin_to_grid(points: np.ndarray) -> np.ndarray:
    kept = []
    occupied = set()
    for x, y in points:
        cell = (int(x) // GRID, int(y) // GRID)
        if cell not in occupied:
            occupied.add(cell)
            kept.append((x, y))
    return np.asarray(kept, dtype=np.float32).reshape(-1, 1, 2)


def lk_pair(previous: np.ndarray, current: np.ndarray):
    raw = cv2.goodFeaturesToTrack(
        previous, maxCorners=0, qualityLevel=0.01, minDistance=4
    )
    if raw is None or len(raw) == 0:
        raise ContractError("goodFeaturesToTrack found no points")
    points0 = thin_to_grid(raw.reshape(-1, 2))
    if len(points0) == 0:
        raise ContractError("10px grid thinning removed every feature")
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.01)
    points1, status_fwd, _ = cv2.calcOpticalFlowPyrLK(
        previous, current, points0, None,
        winSize=(15, 15), maxLevel=2, criteria=criteria,
    )
    back, status_bwd, _ = cv2.calcOpticalFlowPyrLK(
        current, previous, points1, None,
        winSize=(15, 15), maxLevel=2, criteria=criteria,
    )
    if points1 is None or back is None:
        raise ContractError("calcOpticalFlowPyrLK returned None")
    origin = points0.reshape(-1, 2)
    forward = points1.reshape(-1, 2)
    backward = back.reshape(-1, 2)
    fb_error = np.linalg.norm(backward - origin, axis=1)
    keep = (
        status_fwd.reshape(-1).astype(bool)
        & status_bwd.reshape(-1).astype(bool)
        & np.isfinite(origin).all(axis=1)
        & np.isfinite(forward).all(axis=1)
        & (fb_error <= FB_MAX)
    )
    if not keep.any():
        raise ContractError("no points survived the 0.5px forward-backward check")
    displacement = np.linalg.norm(forward[keep] - origin[keep], axis=1)
    return float(displacement.mean()), int(len(points0)), int(keep.sum())


def blob_pair(previous: np.ndarray, current: np.ndarray):
    difference = cv2.GaussianBlur(cv2.absdiff(previous, current), (5, 5), 0)
    _, thresholded = cv2.threshold(
        difference, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )
    opened = cv2.morphologyEx(
        thresholded, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8)
    )
    contours, _ = cv2.findContours(
        opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        raise ContractError("frame-diff produced no contours")
    largest = max(contours, key=cv2.contourArea)
    moments = cv2.moments(largest)
    if moments["m00"] == 0.0:
        raise ContractError("largest contour has zero moment")
    return (
        [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]],
        float(moments["m00"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", required=True, type=Path)
    parser.add_argument("--npz", required=True, type=Path)
    args = parser.parse_args()
    cv2.setNumThreads(1)

    paths, images = load_frames(args.frames)
    tld = load_npz(args.npz)
    space, to_40pct = pick_space(tld)
    log(f"EVIDENCE coordinate_space={space} velocity_px_scale={to_40pct}")
    grays = to_gray(images, space)

    lk_displacements = []
    for index in range(11):
        mean_px, grid_points, kept = lk_pair(grays[index], grays[index + 1])
        lk_displacements.append(mean_px)
        log(
            f"EVIDENCE lk_pair={index}->{index + 1} grid_points={grid_points} "
            f"fb_kept={kept} mean_disp_px={mean_px:.6f}"
        )

    blob_centers = []
    for index in range(11):
        center, area = blob_pair(grays[index], grays[index + 1])
        blob_centers.append(center)
        log(
            f"EVIDENCE blob frame={index + 1} center=({center[0]:.3f},{center[1]:.3f}) "
            f"area_px2={area:.1f}"
        )

    blob_array = np.asarray(blob_centers, dtype=np.float64)
    errors = np.linalg.norm(blob_array - tld[1:], axis=1)
    for index, error in enumerate(errors, start=1):
        log(f"EVIDENCE blob_vs_tld frame={index} err_px={float(error):.3f}")

    lk_velocities = np.asarray(lk_displacements) * to_40pct * FACTOR
    steps = np.linalg.norm(np.diff(blob_array, axis=0), axis=1)
    blob_velocities = steps * to_40pct * FACTOR
    formula = (
        "v = disp_px * 100000/(2*1400*40)"
        if to_40pct == 1.0
        else "v = (disp_px * 0.4) * 100000/(2*1400*40)"
    )

    result = {
        "status": "OK",
        "frame_order": [path.name for path in paths],
        "coordinate_space": space,
        "velocity_px_scale": to_40pct,
        "formula": formula,
        "lk_displacements_px": [float(value) for value in lk_displacements],
        "blob_centers": [[float(x), float(y)] for x, y in blob_centers],
        "blob_vs_tld_err_px": [float(value) for value in errors],
        "blob_err_mean_px": float(errors.mean()),
        "blob_err_max_px": float(errors.max()),
        "velocity_um_min": {
            "lk_mean": float(lk_velocities.mean()),
            "lk_std_ddof0": float(lk_velocities.std(ddof=0)),
            "blob_mean": float(blob_velocities.mean()),
            "hers_tld": HERS_MEAN,
            "hers_tld_std": HERS_STD,
        },
    }
    log(
        "SUMMARY "
        f"space={space} blob_err_mean_px={result['blob_err_mean_px']:.3f} "
        f"blob_err_max_px={result['blob_err_max_px']:.3f} formula={formula!r}"
    )
    log(
        f"SUMMARY lk_mean={result['velocity_um_min']['lk_mean']:.4f} "
        f"lk_std={result['velocity_um_min']['lk_std_ddof0']:.4f} "
        f"blob_mean={result['velocity_um_min']['blob_mean']:.4f} "
        f"hers_tld={HERS_MEAN} +/- {HERS_STD} um/min"
    )

    output = Path(__file__).resolve().with_name("ce_player_video1_results.json")
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    log(f"EVIDENCE results_json={output.name} bytes={output.stat().st_size}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - surface any failure to the log
        message = f"{type(exc).__name__}: {exc}"
        print(f"ERROR {message}", file=sys.stderr, flush=True)
        try:
            output = Path(__file__).resolve().with_name(
                "ce_player_video1_results.json"
            )
            output.write_text(
                json.dumps({"status": "FAILED", "error": message}, indent=2),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
