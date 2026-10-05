"""Score aggregation -> on-chain u16.

STATUS v0.1.0: STUB. The canonical morphology-score formula is NOT present in
any of the four source notebooks (artifact D0437B3E, "Honest gaps"): SSIM scores
and velocity stats exist per-run, but no aggregation to a single morphology score.
Primary source = thesis PDF (Pablo Bravo 2019, asked of b0); fallback = b0's
written pipeline spec. Open decision 2 with Juan (u16 output shape) sits on the
same gap.

Rule until pinned: this package does not emit u16 scores for minting.
"""
from __future__ import annotations

PIPELINE_VERSION = "0.1.0"


def morphology_score(
    *,
    ssim_score: float | None = None,
    velocity_um_min: float | None = None,
    cluster_stats: dict | None = None,
) -> int:
    """Return the u16 morphology score. Formula PENDING - see module docstring."""
    raise NotImplementedError(
        "score formula pending thesis PDF / b0 spec (D0437B3E gap)"
    )
