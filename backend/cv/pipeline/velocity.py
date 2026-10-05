"""Reference: Tracking3HS velocity tracker (micrometers/min time series).

Source: cv/tracking3hs.md, extraction D0437B3E. README-unmapped in Juan's
folder - treat as quantitative/velocity reference until Juan or b0 confirms its
role in the pipeline.

Status notes: uses deprecated skimage.measure.compare_ssim (migrate to
skimage.metrics.structural_similarity) and the legacy OpenCV TLD tracker
(cv2.TrackerTLD_create, removed in OpenCV >=4.5.1 contrib - needs opencv-contrib
legacy or a replacement tracker). Both are port-blockers, flagged here.
"""
from __future__ import annotations

from .config import VelocityParams


def associate_heads(frames_gray, p: VelocityParams):
    """3-frame SSIM/contour/ellipse association -> seed heads. Stub."""
    raise NotImplementedError("stage body lands in v0.2 (extraction D0437B3E)")


def track_velocity(frames, seeds, p: VelocityParams):
    """TLD tracking -> trajectory -> um/min -> (mean, std). Body: v0.2."""
    raise NotImplementedError("stage body lands in v0.2 (extraction D0437B3E)")
