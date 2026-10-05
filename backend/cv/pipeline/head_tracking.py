"""SSIM-based head tracking stage of the TerraQuest CV pipeline.

Provenance: D0437B3E (extracted from ``cv/head_tracking.md``).

Algorithm
---------
Two BGR frames (``2464 x 3280`` in the source notebook capture, taken
~10 minutes apart) are compared to locate the moving head silhouette:

    1. ``cv2.cvtColor(..., cv2.COLOR_BGR2GRAY)`` on both frames.
    2. ``cv2.GaussianBlur`` with ``p.blur_ksize`` on both.
    3. ``skimage.metrics.structural_similarity(cleanA, cleanB, full=True)``
       to obtain the SSIM score plus a per-pixel diff map.
    4. ``(diff * 255).astype(uint8)`` to rescale the diff into the
       0..255 ``uint8`` range expected by ``cv2.threshold``.
    5. ``cv2.threshold(scaled, 0, 255, THRESH_BINARY_INV | THRESH_OTSU)``.
    6. ``cv2.findContours(thresh, RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)``.
    7. For each contour compute spatial moments ``area = m00`` and
       centroid ``(cx, cy) = (m10/m00, m01/m00)``. The score is
       ``exp(p.score_gain * area) / dist_sq`` where
       ``dist_sq = (cx - prev_x)**2 + (cy - prev_y)**2``. A contour is
       excluded (score = 0) when ``area == 0`` or ``dist_sq == 0``
       (the centroid has not moved relative to ``prev_centroid``).
    8. ``argmax`` over the score array; the picked contour's centroid
       and the original SSIM score are returned.

Quirk (preserved from D0437B3E)
------------------------------
The source notebook declared ``(pcx, pcy)`` as the persistent previous
centroid but never updated it across iterations of the criteria loop -
every contour was scored against the same previous centroid for a
given call. This rebuild keeps that semantics explicit by threading
``prev_centroid`` through the public ``track_head`` signature and
leaving the responsibility of updating it to the caller (the
TerraQuest CV pipeline).
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from .config import HeadTrackParams


def track_head(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    p: HeadTrackParams,
    prev_centroid: tuple[float, float] = (0.0, 0.0),
) -> tuple[tuple[float, float] | None, float, np.ndarray | None]:
    """Run the SSIM-based head-tracking stage.

    Parameters
    ----------
    frame_a, frame_b:
        BGR ``uint8`` arrays. In the D0437B3E source they are
        ``2464 x 3280`` JPEGs taken ~10 min apart.
    p:
        ``HeadTrackParams`` carrying ``blur_ksize``, ``score_gain``,
        ``circle_radius`` and ``draw_thickness``.
    prev_centroid:
        ``(x, y)`` centroid threaded across successive ``track_head``
        calls. Defaults to ``(0.0, 0.0)`` exactly as the original
        notebook. ``track_head`` never mutates this value, mirroring
        the D0437B3E quirk where the persistent centroid was not
        updated inside the scoring loop.

    Returns
    -------
    centroid:
        ``(cx, cy)`` of the picked contour as a ``(float, float)``
        tuple, or ``None`` when no contour scored above zero (either
        there were no contours, or every contour was excluded because
        ``area == 0`` or the centroid sat exactly on ``prev_centroid``).
    ssim_score:
        Scalar SSIM score returned by ``structural_similarity``;
        ``float('nan')`` when no candidate was selected.
    chosen_contour:
        The chosen ``cv2.findContours`` output array, or ``None`` when
        no candidate was selected.
    """
    prev_x = float(prev_centroid[0])
    prev_y = float(prev_centroid[1])

    gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)

    ksize = (int(p.blur_ksize), int(p.blur_ksize))
    clean_a = cv2.GaussianBlur(gray_a, ksize, 0)
    clean_b = cv2.GaussianBlur(gray_b, ksize, 0)

    ssim_score, diff = structural_similarity(clean_a, clean_b, full=True)

    scaled = (diff * 255).astype(np.uint8)

    _, thresh = cv2.threshold(
        scaled, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )

    contours, _ = cv2.findContours(
        thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return None, float("nan"), None

    criteria = np.zeros(len(contours), dtype=np.float64)
    centroids: list[tuple[float, float]] = []

    for i, contour in enumerate(contours):
        moments = cv2.moments(contour)
        area = moments["m00"]
        if area == 0:
            centroids.append((0.0, 0.0))
            continue
        cx = moments["m10"] / area
        cy = moments["m01"] / area
        centroids.append((cx, cy))
        dist_sq = (cx - prev_x) ** 2 + (cy - prev_y) ** 2
        if dist_sq == 0:
            criteria[i] = 0.0
        else:
            criteria[i] = math.exp(p.score_gain * area) / dist_sq

    valid_indices = np.flatnonzero(criteria > 0)
    if valid_indices.size == 0:
        return None, float("nan"), None

    best_local = int(np.argmax(criteria[valid_indices]))
    best_idx = int(valid_indices[best_local])

    return (
        centroids[best_idx],
        float(ssim_score),
        contours[best_idx],
    )
