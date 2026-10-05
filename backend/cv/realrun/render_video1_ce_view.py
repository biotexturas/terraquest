#!/usr/bin/env python3
"""Render CE_Player's own DIFFBLOB debug view for the video1 sequence.

Reproduces stage 2 of CE_Player (github.com/mecanosaurio/CE_Player,
src/ofApp.cpp, the en_Simpleblob branch) exactly the way its fbo_C panel
draws it:

    diff = blur11(absdiff(prev, cur)) * ampli(3)
    mask = threshold(diff, 30)   -> white pixel clusters on black

Panel base = that thresholded mask. On top, per detected blob (cFinder
rules: min area = pi*15^2, tracker match radius 100 px):
  - blueSteel bounding rect + white contour polyline,
  - follower trail: red smoothed path, white radius-16 circle, label number,
  - the whiteSmoke statistics block in CE_Player's verbatim format:

        [n]: <label>
        [x]: <rx>    [y]: <ry>
        [v.x]: <vx>  [v.y]: <vy>
        [$]: <area>  [amp]: <amp>

    [amp] is a fresh ofRandom(0, 1) every frame in CE_Player; here it comes
    from a per-blob seeded RNG so re-renders are byte-identical.

Labels persist across steps (nearest center within 100 px inherits the
label). [v.x]/[v.y] = matched label center displacement in px per 2-minute
step (40% coordinate space), 0.0 on first appearance. Trails accumulate
across steps like the live tracker.

Panel 1 = frame 1 (program start state, no diff yet). Panels 2-12 = the 11
diff steps (previous -> current frame) in the run's 40% space (1312x986).
Everything is computed from the real frames, so the image cannot drift from
the run. Header metrics come from the run's own results JSON.
"""

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np

EXPECTED = [f"image{i:04d}.jpg" for i in range(9, 21)]
SPACE_W, SPACE_H = 1312, 986
THUMB_W = 400
AMPLI = 3
DIFF_THRESH = 30
BLUR_K = 11
MIN_AREA = 700.0          # CE_Player cFinder.setMinAreaRadius(15) -> pi*15^2
MAX_MATCH_DIST = 100.0    # CE_Player tracker.setMaximumDistance(100)
BLUE_STEEL = (156, 133, 106)   # ofColor::blueSteel, BGR
WHITE_SMOKE = (245, 245, 245)
TRAIL_RED = (0, 0, 255)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frames", required=True, type=Path)
    p.add_argument(
        "--results",
        type=Path,
        default=Path(__file__).resolve().with_name("ce_player_video1_results.json"),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().with_name("CE_PLAYER_VIDEO1_CE_VIEW.jpg"),
    )
    args = p.parse_args()

    paths = sorted(args.frames.glob("*.jpg"))
    names = [q.name for q in paths]
    if names != EXPECTED:
        raise SystemExit(f"frame order {names} != {EXPECTED}")

    colors, grays = [], []
    for q in paths:
        img = cv2.imread(str(q), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"failed to decode {q.name}")
        img = cv2.resize(img, (SPACE_W, SPACE_H), interpolation=cv2.INTER_AREA)
        colors.append(img)
        grays.append(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))

    # --- CE_Player stage 2 (en_Simpleblob), step by step ----------------
    steps = []          # per step t=1..11: mask, dets, trail snapshot
    label_state = {}    # label -> {"smooth": np, "trail": [np, ...]}
    next_label = 0
    prev_dets = []
    for t in range(1, len(grays)):
        diff = cv2.absdiff(grays[t], grays[t - 1])
        diff = cv2.blur(diff, (BLUR_K, BLUR_K))
        diff = np.clip(diff.astype(np.int16) * AMPLI, 0, 255).astype(np.uint8)
        _, mask = cv2.threshold(diff, DIFF_THRESH, 255, cv2.THRESH_BINARY)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        dets = []
        taken = set()
        for c in contours:
            area = float(cv2.contourArea(c))
            if area < MIN_AREA:
                continue
            x, y, w, h = cv2.boundingRect(c)
            cx, cy = x + w / 2.0, y + h / 2.0
            label = None
            best = None
            for d in prev_dets:
                if d["label"] in taken:
                    continue
                dist = ((cx - d["cx"]) ** 2 + (cy - d["cy"]) ** 2) ** 0.5
                if dist <= MAX_MATCH_DIST and (best is None or dist < best[0]):
                    best = (dist, d)
            if best is not None:
                label = best[1]["label"]
                vx, vy = cx - best[1]["cx"], cy - best[1]["cy"]
            else:
                label = next_label
                next_label += 1
                vx, vy = 0.0, 0.0
            taken.add(label)
            dets.append({
                "label": label, "rect": (x, y, w, h), "cx": cx, "cy": cy,
                "area": area, "contour": c, "vx": vx, "vy": vy,
            })
            st = label_state.setdefault(
                label, {"smooth": np.array([cx, cy], dtype=np.float64), "trail": []}
            )
            st["smooth"] = 0.5 * st["smooth"] + 0.5 * np.array([cx, cy])
            st["trail"].append(st["smooth"].copy())
        steps.append({
            "mask": mask,
            "dets": dets,
            "trails": {lb: list(st["trail"]) for lb, st in label_state.items()},
        })
        prev_dets = dets

    # --- montage -------------------------------------------------------
    scale = THUMB_W / SPACE_W
    thumb_h = int(round(SPACE_H * scale))
    cols, rows, header_h = 4, 3, 50
    canvas = np.full((header_h + rows * thumb_h, cols * THUMB_W, 3), 24, np.uint8)

    line_h = 10
    panels = []  # (image, caption)
    base = cv2.resize(colors[0], (THUMB_W, thumb_h), interpolation=cv2.INTER_AREA)
    panels.append((base, "1/12 image0009 (base frame - diff starts on the next frame)"))

    for idx, step in enumerate(steps, start=1):
        panel = cv2.cvtColor(
            cv2.resize(step["mask"], (THUMB_W, thumb_h), interpolation=cv2.INTER_AREA),
            cv2.COLOR_GRAY2BGR,
        )
        # follower trails (all labels known so far), as the live tracker keeps them
        for label, trail in step["trails"].items():
            pts = (np.asarray(trail, dtype=np.float32) * scale).reshape(-1, 1, 2)
            if len(pts) >= 2:
                cv2.polylines(panel, [pts.astype(np.int32)], False, TRAIL_RED, 2, cv2.LINE_AA)
            c = (int(round(float(pts[-1][0][0]))), int(round(float(pts[-1][0][1]))))
            cv2.circle(panel, c, max(3, int(round(16 * scale))), (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(
                panel, str(label), (c[0] + 5, c[1] + 3),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1, cv2.LINE_AA,
            )
        # blobs: rect, contour, statistics block
        for d in step["dets"]:
            x, y, w, h = d["rect"]
            x1, y1 = int(round(x * scale)), int(round(y * scale))
            x2, y2 = int(round((x + w) * scale)), int(round((y + h) * scale))
            cv2.rectangle(panel, (x1, y1), (x2, y2), BLUE_STEEL, 2, cv2.LINE_AA)
            cnt = (np.asarray(d["contour"], dtype=np.float32) * scale)
            cv2.polylines(
                panel, [cnt.reshape(-1, 1, 2).astype(np.int32)], True,
                (255, 255, 255), 1, cv2.LINE_AA,
            )
            amp = random.Random(9000 + idx * 100 + d["label"]).random()
            lines = [
                f"[n]: {d['label']}",
                f"[x]: {x}    [y]: {y}",
                f"[v.x]: {d['vx']:.1f}    [v.y]: {d['vy']:.1f}",
                f"[$]: {d['area']:.0f}    [amp]: {amp:.2f}",
            ]
            ty = y2 + 6 + line_h  # +20 px in CE_Player's native space
            if ty + line_h * (len(lines) - 1) + 4 > thumb_h:
                ty = max(line_h * len(lines), y1 - 6)
            for j, text in enumerate(lines):
                cv2.putText(
                    panel, text, (x1, ty + j * line_h),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.32, WHITE_SMOKE, 1, cv2.LINE_AA,
                )
        cap = (
            f"{idx + 1}/12 {names[idx]} <- {names[idx - 1]}"
            f"   blobs>=minArea: {len(step['dets'])}"
        )
        panels.append((panel, cap))

    for idx, (img, cap) in enumerate(panels):
        cv2.rectangle(img, (0, thumb_h - 14), (THUMB_W, thumb_h), (0, 0, 0), -1)
        cv2.putText(
            img, cap, (3, thumb_h - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.28,
            (255, 255, 255), 1, cv2.LINE_AA,
        )
        r, c = divmod(idx, cols)
        y = header_h + r * thumb_h
        x = c * THUMB_W
        canvas[y: y + thumb_h, x: x + THUMB_W] = img

    metrics_line = "metrics: ce_player_video1_results.json not found (header line omitted)"
    if args.results.exists():
        try:
            res = json.loads(args.results.read_text(encoding="utf-8"))
            vu = res.get("velocity_um_min", {})
            blob_mean = float(vu.get("blob_mean"))
            hers = float(vu.get("hers_tld"))
            hers_sd = float(vu.get("hers_tld_std"))
            metrics_line = (
                f"blob track v = {blob_mean:.2f} um/min vs Susana TLD {hers:.1f} "
                f"+/- {hers_sd:.1f} ({abs(blob_mean - hers) / hers_sd:.1f} sigma) | "
                f"mean err {float(res.get('blob_err_mean_px')):.1f}px | "
                "clusters below cFinder min area show white but carry no stats block"
            )
        except Exception:
            metrics_line = "metrics: results json unreadable (header line omitted)"

    lines = [
        ("CE_Player output - video1 | its own DIFFBLOB view: absdiff -> blur 11 -> x3 -> thr 30 (ofApp.cpp en_Simpleblob)", (255, 255, 255)),
        ("white = thresholded pixel clusters | blue rect + [n] [x y] [v.x v.y] [$]=area stats = blob | red = follower trail | space 40% (1312x986), dt = 2 min", (170, 170, 170)),
        (metrics_line, (120, 200, 255)),
    ]
    for j, (text, color) in enumerate(lines):
        cv2.putText(
            canvas, text, (8, 16 + j * 15), cv2.FONT_HERSHEY_SIMPLEX, 0.36,
            color, 1, cv2.LINE_AA,
        )

    ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
    if not ok:
        raise SystemExit("jpeg encode failed")
    args.out.write_bytes(buf.tobytes())
    print(
        f"EVIDENCE ce_view={args.out.name} bytes={args.out.stat().st_size} "
        f"dims={canvas.shape[1]}x{canvas.shape[0]} panels={len(panels)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
