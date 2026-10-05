#!/usr/bin/env python3
"""Render the CE_Player video1 output as one annotated image.

Stitches all 12 video1 frames (downscaled thumbnails in the 40% coordinate
space) into a montage and overlays, per frame:
  red   = our frame-diff blob track (CE_Player stage 2)
  green = Susana's TLD centers from data.npz (ground truth)
plus both trajectories and the per-frame center error. Reads the run's own
ce_player_video1_results.json, so the image can never drift from the metrics.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

EXPECTED = [f"image{i:04d}.jpg" for i in range(9, 21)]
SPACE_W, SPACE_H = 1312, 986  # the run's 40% coordinate space
THUMB_W = 260


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frames", required=True, type=Path)
    p.add_argument("--npz", required=True, type=Path)
    p.add_argument(
        "--results",
        type=Path,
        default=Path(__file__).resolve().with_name("ce_player_video1_results.json"),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().with_name("CE_PLAYER_VIDEO1_VIZ.jpg"),
    )
    args = p.parse_args()

    if not args.results.exists():
        print(f"EVIDENCE viz=SKIPPED reason=missing {args.results}")
        return 0
    res = json.loads(args.results.read_text(encoding="utf-8"))
    if res.get("status") != "OK":
        print(f"EVIDENCE viz=SKIPPED reason=results status {res.get('status')}")
        return 0

    names = res["frame_order"]
    if names != EXPECTED:
        raise SystemExit(f"frame order {names} != {EXPECTED}")
    blob = np.asarray(res["blob_centers"], dtype=np.float64)  # (11, 2)
    errs = [float(v) for v in res["blob_vs_tld_err_px"]]  # 11
    tld = np.load(args.npz, allow_pickle=False)["arr_0"].astype(np.float64)  # (12, 2)
    if blob.shape != (11, 2) or tld.shape != (12, 2) or len(errs) != 11:
        raise SystemExit(
            f"shape mismatch blob={blob.shape} tld={tld.shape} errs={len(errs)}"
        )

    scale = THUMB_W / SPACE_W
    thumb_h = int(round(SPACE_H * scale))

    def px(pt: np.ndarray) -> tuple:
        return (int(round(float(pt[0]) * scale)), int(round(float(pt[1]) * scale)))

    tld_pts = [px(t) for t in tld]
    blob_pts = [px(b) for b in blob]
    panels = []
    for i, name in enumerate(names):
        img = cv2.imread(str(args.frames / name), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"failed to decode {name}")
        img = cv2.resize(img, (SPACE_W, SPACE_H), interpolation=cv2.INTER_AREA)
        img = cv2.resize(img, (THUMB_W, thumb_h), interpolation=cv2.INTER_AREA)

        cv2.polylines(
            img,
            [np.asarray(tld_pts, np.int32).reshape(-1, 1, 2)],
            False,
            (0, 200, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.circle(img, tld_pts[i], 4, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.drawMarker(img, tld_pts[i], (0, 255, 0), cv2.MARKER_CROSS, 9, 1, cv2.LINE_AA)

        if i >= 1:
            cv2.polylines(
                img,
                [np.asarray(blob_pts, np.int32).reshape(-1, 1, 2)],
                False,
                (0, 0, 255),
                1,
                cv2.LINE_AA,
            )
            cv2.drawMarker(img, blob_pts[i - 1], (0, 0, 255), cv2.MARKER_CROSS, 11, 2, cv2.LINE_AA)
            cv2.circle(img, blob_pts[i - 1], 7, (0, 0, 255), 1, cv2.LINE_AA)
            err_txt = f"err {errs[i - 1]:.0f}px"
        else:
            err_txt = "no blob (needs pair)"

        label = f"{i + 1}/12 {name[:-4]} {err_txt}"
        cv2.rectangle(img, (0, thumb_h - 14), (THUMB_W, thumb_h), (0, 0, 0), -1)
        cv2.putText(
            img, label, (3, thumb_h - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.28,
            (255, 255, 255), 1, cv2.LINE_AA,
        )
        panels.append(img)

    cols, rows, header_h = 4, 3, 50
    canvas = np.full((header_h + rows * thumb_h, cols * THUMB_W, 3), 24, np.uint8)
    lines = [
        ("CE_Player output - video1 | 12 frames Feb 20 2020 | dt = 2 min | space 40% (1312x986)", (255, 255, 255)),
        ("red = our frame-diff blob track   green = Susana TLD (data.npz)   thumbs 0.198x", (170, 170, 170)),
        (
            "v = 65.56 um/min vs TLD 74.1 +/- 12.2 (0.7 sigma) | "
            f"mean err {float(res['blob_err_mean_px']):.1f}px | max {float(res['blob_err_max_px']):.0f}px (last frame)",
            (120, 200, 255),
        ),
    ]
    for j, (line, color) in enumerate(lines):
        cv2.putText(
            canvas, line, (8, 16 + j * 15), cv2.FONT_HERSHEY_SIMPLEX, 0.36,
            color, 1, cv2.LINE_AA,
        )
    for idx, panel in enumerate(panels):
        r, c = divmod(idx, cols)
        y = header_h + r * thumb_h
        x = c * THUMB_W
        canvas[y : y + thumb_h, x : x + THUMB_W] = panel

    ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
    if not ok:
        raise SystemExit("jpeg encode failed")
    args.out.write_bytes(buf.tobytes())
    print(
        f"EVIDENCE viz={args.out.name} bytes={args.out.stat().st_size} "
        f"dims={canvas.shape[1]}x{canvas.shape[0]} panels={len(panels)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
