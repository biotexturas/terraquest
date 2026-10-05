"""TerraQuest CV pipeline v0.2 - cluster output visualization.

Answers Juan's "can I see an output?" with an actual rendered figure
built from the same code the CI sweep runs: optical-flow arrows on his
Drive frames, plus cluster-label overlays for three (theta, r) settings
from the theta sweep (cv/realrun/THETA_SWEEP.md).

Honesty rules - nothing is silently pinned:
  * score.py stays a stub; no u16 is produced; score_formula = PENDING.
  * r pin stays PENDING - the three cases are shown side by side, none
    is chosen over another; this figure renders, it does not decide.

Output: realrun/CLUSTERS_OUTPUT.png (+ CLUSTERS_OUTPUT.md caption),
committed by .github/workflows/cv-visualize.yml.
"""
from __future__ import annotations

import json
import os

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pipeline import flow as flow_mod
from pipeline.clusters import big_work2
from pipeline.config import ClusterParams, FlowParams
from realrun import N_SAT, SATURNS_ID, fetch_frames

# (theta, r_cells): sweep baseline (singletons), the only multi-cluster
# cell from the sweep (theta 0.1 @ r=1 -> 3 clusters), and its theta twin
# (0.2 @ r=1 -> collapses to 1). Rendered as-is, nothing substituted.
CASES = ((0.1, 0), (0.1, 1), (0.2, 1))
N_CLUSTERS = 20


def blockify(L: np.ndarray, h: int, w: int, res: int) -> np.ndarray:
    """Paint the (nh, nw) label grid back onto the (h, w) frame.

    Cell (i, j) covers rows [i*res, (i+1)*res) and cols [j*res, (j+1)*res) -
    the same indexing flow.assemble_field uses (cell = int(coord / res)).
    NaN cells (no flow coverage) stay -1 = transparent.
    """
    img = np.full((h, w), -1.0, dtype=np.float64)
    nh, nw = L.shape
    for i in range(nh):
        y0 = i * res
        y1 = min(y0 + res, h)
        if y0 >= h:
            break
        for j in range(nw):
            x0 = j * res
            x1 = min(x0 + res, w)
            if x0 >= w:
                break
            v = float(L[i, j])
            if v == v:  # not NaN
                img[y0:y1, x0:x1] = v
    return img


def stats(L: np.ndarray) -> dict:
    fin = L[~np.isnan(L)]
    if fin.size == 0:
        return {"labels_found": 0, "labeled_cells": 0, "largest": 0}
    uniq, counts = np.unique(fin, return_counts=True)
    return {
        "labels_found": int(uniq.size),
        "labeled_cells": int(fin.size),
        "largest": int(counts.max()),
    }


def colorize(lab: np.ndarray) -> np.ndarray:
    """RGBA overlay: tab20 color per cluster label, transparent where -1."""
    cmap = plt.get_cmap("tab20")
    rgba = np.zeros((*lab.shape, 4), dtype=np.float64)
    mask = lab >= 0
    if mask.any():
        cols = cmap((lab[mask] % 20) / 20.0)
        rgba[mask, :3] = cols[:, :3]
        rgba[mask, 3] = 0.72
    return rgba


def main() -> None:
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "realrun")
    sat = fetch_frames(SATURNS_ID, os.path.join(base, "pictures_Saturns"), N_SAT)
    if len(sat) < 3:
        raise SystemExit(f"need >=3 Saturns frames, got {len(sat)}")
    folder = os.path.dirname(sat[0])

    g0 = cv2.imread(sat[0], cv2.IMREAD_GRAYSCALE)
    g1 = cv2.imread(sat[1], cv2.IMREAD_GRAYSCALE)
    if g0 is None or g1 is None:
        raise SystemExit("failed to read fetched frames")
    h, w = g0.shape
    fp = FlowParams()

    # Optical flow between frame 0 and 1 (same call the pipeline stages use).
    # calc_flow returns (M, 1, 2) point stacks (grid_points keeps a middle
    # axis); flatten to (M, 2) before column access - same as assemble_field.
    old, new = flow_mod.calc_flow(g0, g1, fp)
    old = old.reshape(-1, 2)
    new = new.reshape(-1, 2)
    dx = new[:, 0] - old[:, 0]
    dy = new[:, 1] - old[:, 1]
    # Thin the arrows so the panel stays readable on big frames.
    step = max(1, len(old) // 400)

    fig, axs = plt.subplots(2, 2, figsize=(14, 11))
    fig.suptitle(
        "cv-pipeline v0.2 cluster output - Juan's Drive frames (pictures_Saturns)\n"
        "rendered by cv/visualize.py; r and score_formula both stay PENDING",
        fontsize=13,
    )

    ax = axs[0][0]
    ax.imshow(g0, cmap="gray")
    ax.quiver(
        old[::step, 0], old[::step, 1], dx[::step], dy[::step],
        angles="xy", scale_units="xy", scale=1.0, color="#00e5ff",
        width=0.0025, headwidth=3.5,
    )
    ax.set_title(f"optical flow (frame 0->1): {len(old)} good vectors, res={fp.res}px")

    report = {
        "pipeline_version": "cv-pipeline v0.2",
        "generated_by": "cv/visualize.py (.github/workflows/cv-visualize.yml)",
        "source": "Juan Drive Paenibacillus_tracking (public), fetched in CI",
        "score_formula": "PENDING (score.py stub; no u16 produced)",
        "r_pin": "PENDING - cases rendered side by side, none chosen",
        "grid": [int(h // fp.res), int(w // fp.res)],
        "good_flow_vectors": int(len(old)),
        "cases": {},
    }

    slots = (axs[0][1], axs[1][0], axs[1][1])
    for (theta, r), ax in zip(CASES, slots):
        L = big_work2(N_CLUSTERS, folder, 0, ClusterParams(r=r, theta=theta), fp)
        st = stats(L)
        lab = blockify(L, h, w, fp.res)
        ax.imshow(g0, cmap="gray")
        ax.imshow(colorize(lab), interpolation="nearest")
        ax.set_title(
            f"theta={theta}, r={r} ({r * fp.res}px window): "
            f"{st['labels_found']} clusters, largest {st['largest']} cells"
        )
        ax.axis("off")
        rec = {
            "theta": theta,
            "r_cells": r,
            "r_window_px": r * fp.res,
            **st,
            "grid": [int(x) for x in L.shape],
        }
        report["cases"][f"theta{theta}_r{r}"] = rec
        print("case_%s_%s: %s" % (theta, r, json.dumps(rec)))

    for ax in axs.ravel():
        ax.set_xticks([])
        ax.set_yticks([])
    fig.tight_layout(rect=(0, 0, 1, 0.95))

    png = os.path.join(base, "CLUSTERS_OUTPUT.png")
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"CLUSTERS_OUTPUT.png written ({os.path.getsize(png)} bytes)")

    md = [
        "# cv-pipeline v0.2 - cluster output figure",
        "",
        "Rendered by cv/visualize.py (workflow cv-visualize.yml) on Juan's public",
        "Drive frames (pictures_Saturns). Same big_work2 code path as the theta",
        "sweep - this figure renders the output, it does not pin anything.",
        "score_formula and r both stay PENDING per cv/README.md.",
        "",
        "![cluster output](CLUSTERS_OUTPUT.png)",
        "",
        "```json",
        json.dumps(report, indent=2, default=str),
        "```",
        "",
    ]
    with open(os.path.join(base, "CLUSTERS_OUTPUT.md"), "w") as fh:
        fh.write("\n".join(md))
    print("CLUSTERS_OUTPUT.md written")


if __name__ == "__main__":
    main()
