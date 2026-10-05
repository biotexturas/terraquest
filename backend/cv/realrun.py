"""TerraQuest CV pipeline v0.2 - real-footage run (lane two).

Fetches frames from Juan's public Drive folder Paenibacillus_tracking,
runs the cluster stage (pictures_Saturns) and the head-tracking stage
(pictures_ArrowHead) end to end, writes realrun/RESULTS.md.

Pins still PENDING (never silently substituted):
  * score_formula - score.py is a stub; no u16 produced.
  * ClusterParams.r - demo r=0 reported as-is; one clearly labeled
    exploratory variant (r=2) beside it, never instead of it.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

import cv2
import numpy as np

from pipeline import flow as flow_mod
from pipeline.clusters import big_work2
from pipeline.config import ClusterParams, FlowParams, HeadTrackParams
from pipeline.head_tracking import track_head

SATURNS_ID = "1GSKCth90fDqEKGn0PU4bx6ptif1KTx0v"
ARROWHEAD_ID = "16Jme86qbn-i4sTUChNZVpoEy92uSOf2j"
N_SAT = 5
N_AH = 4
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) cv-realrun/0.2"}


def get(url: str) -> bytes:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=180
    ).read()


def list_folder(folder_id: str):
    html = get(f"https://drive.google.com/drive/folders/{folder_id}").decode(
        "utf-8", "replace"
    )
    m = re.search(r"window\['_DRIVE_ivd'\] = '(.*?)';", html, re.S)
    if not m:
        raise RuntimeError(f"Drive listing parse failed: {folder_id}")
    data = json.loads(m.group(1).encode().decode("unicode_escape"))
    out = []
    for e in data[0]:
        if e[3] in ("image/jpeg", "image/png") or str(e[2]).lower().endswith(
            (".jpg", ".jpeg", ".png")
        ):
            out.append((e[0], e[2]))
    out.sort(key=lambda t: t[1])
    return out


def fetch_frames(folder_id: str, dest: str, n: int):
    os.makedirs(dest, exist_ok=True)
    items = list_folder(folder_id)
    print(f"{os.path.basename(dest)}: {len(items)} images listed")
    paths = []
    for fid, name in items[:n]:
        path = os.path.join(dest, name)
        with open(path, "wb") as fh:
            fh.write(get(f"https://drive.google.com/uc?export=download&id={fid}"))
        paths.append(path)
    print(f"  downloaded {len(paths)} frames -> {dest}")
    return paths


def run_clusters(sat_paths):
    folder = os.path.dirname(sat_paths[0])
    fp = FlowParams()
    cp = ClusterParams()
    g = [cv2.imread(p, cv2.IMREAD_GRAYSCALE) for p in sat_paths[:3]]
    old0, _new0 = flow_mod.calc_flow(g[0], g[1], fp)
    old1, _new1 = flow_mod.calc_flow(g[1], g[2], fp)
    stats = {
        "flow_params": {"res": fp.res, "win": fp.win, "levels": fp.levels},
        "good_vectors_pair01": int(len(old0)),
        "good_vectors_pair12": int(len(old1)),
        "runs": {},
    }
    for label, p in (("demo_r0", cp), ("exploratory_r2", ClusterParams(r=2))):
        L = big_work2(cp.n_clusters, folder, 0, p, fp)
        fin = L[~np.isnan(L)]
        uniq, counts = np.unique(fin, return_counts=True)
        rec = {
            "r": p.r,
            "theta": p.theta,
            "vmin": p.vmin,
            "vmax": p.vmax,
            "n_clusters": p.n_clusters,
            "grid": [int(x) for x in L.shape],
            "labels_found": int(uniq.size),
            "labeled_cells": int(fin.size),
            "sizes": {str(int(u)): int(c) for u, c in zip(uniq, counts)},
        }
        stats["runs"][label] = rec
        np.save(os.path.join(os.path.dirname(folder), f"clusters_{label}.npy"), L)
        print(f"clusters_{label}: {json.dumps(rec)}")
    return stats


def run_head(ah_paths):
    hp = HeadTrackParams()
    prev = (0.0, 0.0)
    pairs = []
    for i in range(len(ah_paths) - 1):
        a = cv2.imread(ah_paths[i], cv2.IMREAD_COLOR)
        b = cv2.imread(ah_paths[i + 1], cv2.IMREAD_COLOR)
        centroid, ssim, contour = track_head(a, b, hp, prev_centroid=prev)
        area = float(cv2.moments(contour)["m00"]) if contour is not None else 0.0
        rec = {
            "pair": [os.path.basename(ah_paths[i]), os.path.basename(ah_paths[i + 1])],
            "ssim": None if ssim != ssim else round(float(ssim), 6),
            "centroid": None
            if centroid is None
            else [round(float(centroid[0]), 1), round(float(centroid[1]), 1)],
            "chosen_area_px": round(area, 1),
        }
        pairs.append(rec)
        print(f"head {json.dumps(rec)}")
        if centroid is not None:
            prev = centroid
    return {"blur_ksize": hp.blur_ksize, "score_gain": hp.score_gain, "pairs": pairs}


def main() -> None:
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "realrun")
    os.makedirs(base, exist_ok=True)
    sat = fetch_frames(SATURNS_ID, os.path.join(base, "pictures_Saturns"), N_SAT)
    ah = fetch_frames(ARROWHEAD_ID, os.path.join(base, "pictures_ArrowHead"), N_AH)
    if len(sat) < 3:
        raise SystemExit(f"need >=3 Saturns frames, got {len(sat)}")
    if len(ah) < 2:
        raise SystemExit(f"need >=2 ArrowHead frames, got {len(ah)}")
    report = {
        "pipeline_version": "cv-pipeline v0.2",
        "score_formula": "PENDING (score.py stub; no u16 produced)",
        "r_pin": "PENDING (demo r=0 as-is; r=2 variant exploratory only)",
        "source": "Juan Drive Paenibacillus_tracking (public), fetched in CI",
        "stages": {},
    }
    report["stages"]["flow+clusters"] = run_clusters(sat)
    report["stages"]["head_tracking"] = run_head(ah)
    md = [
        "# cv-pipeline v0.2 real-footage run",
        "",
        "Generated by .github/workflows/cv-realrun.yml on Juan's public Drive",
        "frames. score_formula and ClusterParams.r remain PENDING - see the",
        "cv/README.md convention lines.",
        "",
        "```json",
        json.dumps(report, indent=2, default=str),
        "```",
        "",
    ]
    with open(os.path.join(base, "RESULTS.md"), "w") as fh:
        fh.write("\n".join(md))
    print("RESULTS.md written")


if __name__ == "__main__":
    main()
