pipeline_version = cv-pipeline v0.2 + ce_player_video1 v0.1 (CE_Player params verbatim)
score_formula = PENDING (this run validates tracked centers, not the u16 score)
delta_t = 2 minutes per frame (Informe 1 verbatim; notebook factor 100000/(2*scale*scale_percent), the 2 = time step)
frame_order = sorted(glob('./pictures/*.jpg')) -> image0009..image0020, 12 frames

# CE_Player video1 validation run

## Run status

**Complete - real data, CI-computed, no fabricated values.** Workflow
`realrun-video1` run 1 concluded **success**; the runner executed end to end
and committed `cv/realrun/ce_player_video1_results.json` and
`cv/realrun/ce_player_video1_run_log.txt` at commit `14eb48b`. Every number
below comes from that run's log.

Path of execution: my compute sandbox had no network (DNS failures), so the
run moved into GitHub Actions, which downloads the 12 frames + npz from
Susana's shared Drive, runs both stages, and commits the results back to this
directory. CI-authored commits use GITHUB_TOKEN and cannot retrigger
workflows, so there is no commit loop.

## Input verification evidence

- 12 frames, byte sizes 4,259,183 - 4,361,970 (contract 3.0-5.5 MB), all
decode 3280x2464, order image0009 -> image0020 verified against the
`sorted(glob)` convention.
- `data.npz`: 456 bytes, key `arr_0`, shape (12, 2), float64, value range
[158.334274, 938.5].

## Coordinate space

**40% resize (1312x986) - npz space, velocity_px_scale = 1.0.**
Evidence: TLD centers span x = [262.0, 938.5], y = [158.334, 887.0] - all
below the 1400/1000 bounds, matching her crop + resize-40% pipeline, so the
notebook factor applies directly to processing pixels.

## Stage 1 - Lucas-Kanade optical flow

CE_Player params verbatim: `goodFeaturesToTrack(qualityLevel=0.01,
minDistance=4)` + 10px grid thinning; `calcOpticalFlowPyrLK(winSize=(15,15),
maxLevel=2, criteria=(EPS|COUNT,10,0.01))`; forward-backward rejection at
0.5 px.

| Pair | Frames | Grid points | FB kept | Mean disp (px) |
|---:|---|---:|---:|---:|
| 0 | 0009->0010 | 465 | 167 | 2.293409 |
| 1 | 0010->0011 | 650 | 163 | 0.871458 |
| 2 | 0011->0012 | 645 | 123 | 1.142603 |
| 3 | 0012->0013 | 705 | 160 | 1.518169 |
| 4 | 0013->0014 | 705 | 176 | 1.360365 |
| 5 | 0014->0015 | 870 | 256 | 0.880256 |
| 6 | 0015->0016 | 1029 | 358 | 1.418972 |
| 7 | 0016->0017 | 1055 | 374 | 2.154039 |
| 8 | 0017->0018 | 1205 | 444 | 2.111675 |
| 9 | 0018->0019 | 1587 | 341 | 4.765700 |
| 10 | 0019->0020 | 1546 | 592 | 1.627912 |

LK mean = 1.635 px, std(ddof=0) = 0.926 px over the 11 pairs. FB rejection
is heavy (123-592 of 465-1587 survivors) - see observations.

## Stage 2 - frame-diff blob

absdiff -> GaussianBlur(5,5) -> Otsu -> open 3x3 -> largest-contour centroid,
assigned to frame i+1.

| Frame | Center (px, 40% space) | Contour area (px^2) | Error vs TLD (px) |
|---:|---|---:|---:|
| 1 | (720.888, 191.571) | 7272.0 | 26.093 |
| 2 | (742.252, 262.630) | 7392.5 | 40.357 |
| 3 | (769.509, 327.253) | 7869.0 | 55.542 |
| 4 | (791.715, 394.880) | 7980.5 | 73.562 |
| 5 | (820.537, 464.600) | 7634.5 | 63.472 |
| 6 | (843.280, 532.941) | 7772.0 | 79.999 |
| 7 | (871.968, 602.945) | 7772.0 | 53.519 |
| 8 | (893.183, 670.801) | 8314.0 | 73.614 |
| 9 | (925.022, 739.070) | 8475.5 | 78.109 |
| 10 | (956.049, 808.719) | 8579.5 | 80.224 |
| 11 | (983.625, 876.282) | 9212.0 | **778.195** |

Frames 1-10: mean 62.4 px, max 80.2 px. Including frame 11: mean 127.5 px,
max 778.2 px. Frame 0 excluded from comparison (no incoming diff).

## Velocity comparison

`v = disp_px * 100000/(2*1400*40)` - processing already in the 40% npz
space; the divisor 2 is the two-minute time step.

| Source | Mean (um/min) | Std (um/min) |
|---|---:|---:|
| Ours - LK (11 pairs, scene-level) | 1.64 | 0.93 |
| Ours - frame-diff blob (10 steps) | **65.56** | - |
| Susana - TLD | 74.1 | 12.2 |

**Headline: blob velocity is 8.5 um/min below her TLD mean - inside one
standard deviation of her run (0.7 sigma).**

## Honest observations

- **LK is a scene statistic here, not a head tracker.** The reported mean is
over all surviving features across the whole frame; static colony/substrate
texture contributes ~0, and the fast-moving head features are largely the
ones the 0.5px FB check rejects (only 123-592 survivors per pair). Result:
1.6 um/min, 45x below her head velocity. This quantitatively confirms the
pre-run caveat - CE_Player's LK was tuned for 29fps video, and as a
global mean over 2-minute gaps it cannot stand in for her TLD tracker. Per-pair
displacements (0.87-4.77 px) are recorded for completeness, not as velocity
estimates.
- **The frame-diff blob is the load carrier**, as predicted before the run:
its velocity lands within 1 sigma of her TLD (65.56 vs 74.1 +/- 12.2).
- **Blob center vs TLD center:** frames 1-10 average 62.4 px (~156 original
px). The blob centroid is the center of the whole moving region (7.3k-9.2k
px^2), not the head box TLD fits - a systematic offset of this order is
expected. Tightening this is exactly what fixture step 5 in
`HOMESCOPE_NOTE.md` (pick theta/r by npz diff) is for.
- **Frame 11 outlier (778 px):** our blob track is smooth through the last
pair (final step 73 px, in-family with the ~70-77 px steps before it) while
the error explodes - so the divergence sits on TLD's frame-11 position. Her
notebook records video1's last frame with the tracking box shrinking, so a
degraded final-frame TLD center is the leading hypothesis; a blob region
switch on the last pair (area peaks at 9212 px^2) is the alternative. Not
resolvable from numbers alone - eyeball against `output.avi` in fixture step
1. The velocity conclusion is unaffected: blob_mean uses the 10 inter-center
steps, all of which are smooth.
- `score_formula` stays PENDING - this run validates tracked centers, not the
u16 score. Nothing on-chain; program and IDL untouched.

## Reproduction

```bash
# local (needs the Drive files)
python cv/realrun/ce_player_video1.py --frames ./pictures --npz ./data.npz
# CI: Actions -> realrun-video1 -> Run workflow, or push to cv/realrun/
```
