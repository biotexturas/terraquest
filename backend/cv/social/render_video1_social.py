#!/usr/bin/env python3
"""Render a social-media timelapse video of CE_Player's video1 analysis.

Input : the 12 raw time-lapse frames (image0009..image0020) downloaded to
        --frames, plus the run's results JSON (ce_player_video1_results.json).
Output: H.264 MP4, 1440x1080 (4:3, even dims for yuv420p), 30 fps, ~23 s.

Per time-lapse step the video shows the raw color frame with CE_Player
stage-2 analysis drawn on top: the same absdiff -> blur 11 -> x3 -> thr 30
thresholded motion clusters (white blend), blue blob rects + contour +
centroid, label numbers, red follower trails, and the [n]/[x y]/[v.x v.y]/
[$]/[amp] stats block that CE_PLAYER_VIDEO1_CE_VIEW.jpg shows. Stage-2 is
recomputed with the run's exact parameters and the per-label seeded amp, so
numbers match the CE_VIEW render; metrics/intro/outro numbers come from the
committed results JSON.

Overlay math runs in the run's 40%% space (1312x986), scaled to the output
canvas by sx = OUT_W/SPACE_W, sy = OUT_H/SPACE_H. ASCII-only text - cv2
Hershey fonts render no unicode.

Usage:
  python cv/social/render_video1_social.py \
    --frames RUNNER_TEMP/pictures \
    --results cv/realrun/ce_player_video1_results.json \
    --out cv/realrun/CE_PLAYER_VIDEO1_TIMELAPSE.mp4
"""

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

# --- run constants (identical to cv/realrun/render_video1_ce_view.py) ------
SPACE_W, SPACE_H = 1312, 986   # 40% processing space
AMPLI = 3
DIFF_THRESH = 30
BLUR_K = 11
MIN_AREA = 700.0               # setMinAreaRadius(15) -> pi*15^2
MAX_MATCH_DIST = 100.0

# --- video constants ------------------------------------------------------
OUT_W, OUT_H = 1440, 1080
FPS = 30
HOLD = 42                      # frames per time-lapse step (1.4 s)
INTRO = 75                     # 2.5 s
OUTRO = 105                    # 3.5 s
HEADER_H = 126
FOOTER_H = 64

BLUE_STEEL = (156, 133, 106)
WHITE_SMOKE = (245, 245, 245)
TRAIL_RED = (0, 0, 255)
GRAY_TXT = (170, 170, 170)
CYAN_TXT = (200, 255, 255)
BLACK = (0, 0, 0)
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_S = cv2.FONT_HERSHEY_DUPLEX
AA = cv2.LINE_AA


def load_frames(frame_dir: Path):
    paths = sorted(frame_dir.glob("*.jpg"))
    if len(paths) != 12:
        raise SystemExit(f"expected 12 frames in {frame_dir}, found {len(paths)}")
    colors, grays = [], []
    for q in paths:
        img = cv2.imread(str(q), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"failed to decode {q.name}")
        img = cv2.resize(img, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
        small = cv2.resize(img, (SPACE_W, SPACE_H), interpolation=cv2.INTER_AREA)
        colors.append(img)
        grays.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
    return paths, colors, grays


def stage2(grays):
    """CE_Player stage 2, step by step - replica of the CE_VIEW render."""
    steps = []
    prev_dets = []
    label_state = {}
    next_label = 0
    for t in range(1, len(grays)):
        diff = cv2.absdiff(grays[t], grays[t - 1])
        # sigmaX=0 computes sigma from ksize (identical to the 2-arg form in
        # OpenCV 4; OpenCV 5's Python binding makes sigmaX required)
        diff = cv2.GaussianBlur(diff, (BLUR_K, BLUR_K), 0)
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
                "vx": vx, "vy": vy, "area": area, "contour": c,
            })
        for d in dets:
            st = label_state.setdefault(d["label"], {
                "smooth": np.array([d["cx"], d["cy"]], dtype=np.float64),
                "trail": [],
            })
            st["smooth"] = 0.5 * st["smooth"] + 0.5 * np.array([d["cx"], d["cy"]])
            st["trail"].append(st["smooth"].copy())
        steps.append({"frame": t, "mask": mask, "dets": dets})
        prev_dets = dets
    return steps, label_state


def put_right(img, text, y, scale, color, font=FONT, thick=1):
    (w, _), _ = cv2.getTextSize(text, font, scale, thick)
    cv2.putText(img, text, (OUT_W - 8 - w, y), font, scale, color, thick, AA)


def put_center(img, text, y, scale, color, font=FONT, thick=2):
    (w, _), _ = cv2.getTextSize(text, font, scale, thick)
    cv2.putText(img, text, ((OUT_W - w) // 2, y), font, scale, color, thick, AA)


def metrics_line(res):
    try:
        vu = res["velocity_um_min"]
        blob = float(vu["blob_mean"])
        hers = float(vu["herr_tld"])
        sd = float(vu["herr_tld_std"])
        err = float(res.get("blob_err_mean_px", 0.0))
        sig = (blob - hers) / sd
        return (
            f"blob track {blob:.2f} um/min vs Susana TLD {hers:.1f}+/-{sd:.1f} "
            f"({sig:.1f} sigma) | mean err {err:.1f} px | "
            "sub-min clusters show white, no stats block"
        )
    except Exception:
        return "metrics: results json unreadable (header omitted)"


def draw_header(img, idx, n, ml):
    cv2.rectangle(img, (0, 0), (OUT_W, HEADER_H), BLACK, -1)
    cv2.putText(
        img,
        f"CE_Player output - video1 | absdiff -> blur {BLUR_K} -> x{AMPLI} -> "
        f"thr {DIFF_THRESH} (en_SimpleBlob)",
        (8, 36), FONT, 1.0, WHITE_SMOKE, 2, AA,
    )
    cv2.putText(
        img,
        "white = thresholded pixel clusters | blue rect + [n] [x y] = blob stats | "
        "red = follower trail | space 40% (1312x986), dt = 2 min",
        (8, 72), FONT, 0.7, GRAY_TXT, 1, AA,
    )
    cv2.putText(img, ml, (8, 106), FONT, 0.7, CYAN_TXT, 1, AA)


def draw_footer(img, idx, n):
    cv2.rectangle(img, (0, OUT_H - FOOTER_H), (OUT_W, OUT_H), BLACK, -1)
    cv2.putText(
        img,
        "Data: Susana Marquez microcosm (video1) | analysis: CE_Player | TerraQuest",
        (8, OUT_H - 22), FONT, 0.7, WHITE_SMOKE, 1, AA,
    )
    put_right(img, f"frame {idx:02d}/{n}", OUT_H - 22, 0.8, WHITE_SMOKE)


def draw_clock(img, idx):
    clock = "t = 0 min (baseline)" if idx == 1 else f"t + {2 * (idx - 1)} min"
    org = (14, OUT_H - FOOTER_H - 26)
    cv2.putText(img, clock, org, FONT, 1.6, BLACK, 6, AA)
    cv2.putText(img, clock, org, FONT, 1.6, WHITE_SMOKE, 3, AA)


def compose_base(base, step, sx, sy, label_state):
    """Draw CE_Player stage-2 overlay onto the raw color frame."""
    img = base.copy()
    if step is None:
        return img
    # thresholded motion clusters as a white glow on the photo
    m = cv2.resize(step["mask"], (OUT_W, OUT_H), interpolation=cv2.INTER_NEAREST)
    sel = m > 0
    if sel.any():
        pix = img[sel].astype(np.float32)
        img[sel] = np.clip(0.55 * pix + 0.45 * 255.0, 0, 255).astype(np.uint8)
    # follower trails (all labels known so far)
    for _label, st in label_state.items():
        if not st["trail"]:
            continue
        pts = np.asarray(st["trail"], dtype=np.float32)
        pts = np.stack([pts[:, 0] * sx, pts[:, 1] * sy], axis=1)
        if len(pts) >= 2:
            cv2.polylines(img, [pts.astype(np.int32)], False, TRAIL_RED, 3, AA)
        head = (int(round(float(pts[-1][0]))), int(round(float(pts[-1][1]))))
        cv2.circle(img, head, max(6, int(round(16 * sx))), WHITE_SMOKE, 2, AA)
        cv2.putText(
            img, str(_label), (head[0] + 5, head[1] + 4),
            FONT, 0.8, WHITE_SMOKE, 2, AA,
        )
    # per-blob rects, contours, centroids, labels, stats
    for d in step["dets"]:
        x, y, w, h = d["rect"]
        x1, y1 = int(round(x * sx)), int(round(y * sy))
        x2, y2 = int(round((x + w) * sx)), int(round((y + h) * sy))
        cv2.rectangle(img, (x1, y1), (x2, y2), BLUE_STEEL, 3, AA)
        cont = d["contour"].reshape(-1, 2).astype(np.float32)
        cont = np.stack([cont[:, 0] * sx, cont[:, 1] * sy], axis=1)
        cv2.polylines(img, [cont.astype(np.int32)], True, WHITE_SMOKE, 2, AA)
        c = (int(round(d["cx"] * sx)), int(round(d["cy"] * sy)))
        cv2.circle(img, c, 5, WHITE_SMOKE, -1, AA)
        cv2.putText(img, str(d["label"]), (c[0] + 6, c[1] - 4), FONT, 0.75, WHITE_SMOKE, 2, AA)
        # stats block, CE_Player native format (seeded amp = byte-identical rerender)
        amp = random.Random(9000 + d["step"] * 100 + d["label"]).random()
        lines = [
            f"[n]: {d['label']}",
            f"[x]: {d['cx']:.1f}    [y]: {d['cy']:.1f}",
            f"[v.x]: {d['vx']:.1f}   [v.y]: {d['vy']:.1f}",
            f"[$]: {d['area']:.0f}   [amp]: {amp:.2f}",
        ]
        line_h, font = 26, 0.95
        tx = x1
        ty = y2 + 6 + line_h
        if ty + line_h * (len(lines) - 1) > OUT_H - FOOTER_H:
            ty = max(HEADER_H + line_h, y1 - 6)
        for j, text in enumerate(lines):
            cv2.putText(img, text, (tx, ty + j * line_h), FONT_S, font, WHITE_SMOKE, 1, AA)
    return img


def intro_frame(ml):
    img = np.full((OUT_H, OUT_W, 3), (28, 26, 30), np.uint8)
    put_center(img, "TerraQuest x CE_Player", 330, 1.8, WHITE_SMOKE)
    put_center(img, "Susana's microcosm time-lapse, video1 - analyzed by CE_Player", 430, 1.0, WHITE_SMOKE)
    put_center(img, "12 frames | dt = 2 min | 4x scope (0.714 um/px) | 22 min span", 494, 0.9, GRAY_TXT)
    put_center(img, "motion clusters + blob boxes + follower trails drawn on every frame", 556, 0.8, GRAY_TXT)
    put_center(img, "cv-pipeline v0.2 + ce_player_video1 v0.1", 640, 0.75, CYAN_TXT)
    return img


def outro_frame(res):
    img = np.full((OUT_H, OUT_W, 3), (28, 26, 30), np.uint8)
    put_center(img, "Motion is real", 300, 1.6, WHITE_SMOKE)
    try:
        vu = res["velocity_um_min"]
        blob = float(vu["blob_mean"])
        hers = float(vu["herr_tld"])
        sd = float(vu["herr_tld_std"])
        lk = float(vu["lk_mean"])
        sig = (blob - hers) / sd
        put_center(
            img,
            f"blob track {blob:.1f} um/min vs Susana's TLD {hers:.1f} +/- {sd:.1f} um/min ({sig:.1f} sigma)",
            400, 1.0, WHITE_SMOKE,
        )
        put_center(img, f"frame-diff blob carries the motion | LK scene-static mean {lk:.1f} um/min", 462, 0.9, GRAY_TXT)
    except Exception:
        put_center(img, "metrics from ce_player_video1_results.json unavailable", 400, 0.9, GRAY_TXT)
    put_center(img, "score formula PENDING | data: Susana Marquez | analysis: CE_Player", 540, 0.8, GRAY_TXT)
    put_center(img, "TerraQuest | keymerlab.nl | biotexturas.org", 600, 0.8, CYAN_TXT)
    return img


def emit(proc, img, n):
    buf = img.tobytes()
    for _ in range(n):
        proc.stdin.write(buf)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", required=True, type=Path)
    ap.add_argument("--results", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    try:
        res = json.loads(args.results.read_text(encoding="utf-8"))
    except Exception:
        res = {}
    ml = metrics_line(res)

    paths, colors, grays = load_frames(args.frames)
    steps, label_state = stage2(grays)
    # attach step number (1..11) for the seeded amp, mirroring CE_VIEW enumerate(..., 1)
    for i, st in enumerate(steps, start=1):
        for d in st["dets"]:
            d["step"] = i

    sx, sy = OUT_W / SPACE_W, OUT_H / SPACE_H
    n = len(paths)
    total_frames = INTRO + n * HOLD + OUTRO
    total_sec = total_frames / FPS
    fade_out = max(0.0, total_sec - 0.6)
    print(
        f"frames={n} steps={len(steps)} dets/step="
        f"{[len(s['dets']) for s in steps]} total={total_frames} "
        f"({total_sec:.1f}s) out={args.out}",
        flush=True,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{OUT_W}x{OUT_H}", "-r", str(FPS), "-i", "-",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-shortest",
        "-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out:.2f}:d=0.6",
        "-movflags", "+faststart",
        str(args.out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        emit(proc, intro_frame(ml), INTRO)
        # baseline frame (frame 1, no diff yet)
        base = compose_base(colors[0], None, sx, sy, label_state)
        draw_header(base, 1, n, ml)
        draw_footer(base, 1, n)
        draw_clock(base, 1)
        emit(proc, base, HOLD)
        print("step 01: baseline emitted", flush=True)
        for i, st in enumerate(steps, start=1):
            img = compose_base(colors[st["frame"]], st, sx, sy, label_state)
            disp = i + 1
            draw_header(img, disp, n, ml)
            draw_footer(img, disp, n)
            draw_clock(img, disp)
            emit(proc, img, HOLD)
            print(f"step {disp:02d}: dets={len(st['dets'])} emitted {HOLD} frames", flush=True)
        emit(proc, outro_frame(res), OUTRO)
        proc.stdin.close()
    except BrokenPipeError:
        err = proc.stderr.read().decode("utf-8", "replace")
        raise SystemExit(f"ffmpeg pipe broke:\n{err}")
    rc = proc.wait()
    if rc != 0:
        err = proc.stderr.read().decode("utf-8", "replace")
        raise SystemExit(f"ffmpeg failed rc={rc}:\n{err}")

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration,size:stream=width,height,codec_name",
            "-of", "default=nw=1", str(args.out),
        ],
        capture_output=True, text=True,
    )
    print(probe.stdout, flush=True)
    size = args.out.stat().st_size
    if size < 500_000:
        raise SystemExit(f"mp4 too small: {size} bytes")
    print(f"EVIDENCE social_timelapse bytes={size} total={total_sec:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
