# Homescope note - Marquez filter mapping & validation fixture plan

delta_t = 2 minutes per frame (Informe 1 verbatim; notebook factor 100000/(2*scale*scale_percent), the 2 = time step)
frame_order = sorted(glob('./pictures/*.jpg')) -> image0009..image0020, 12 frames (video1; image0008 sits at the video1 root outside the sequence)

Status: documentation only, no code change. Sits beside `cv/realrun/CLUSTERS_OUTPUT.md` (the theta 0.1 / 0.2 comparison). Per `cv/README` convention: `pipeline_version = cv-pipeline v0.2` (unchanged), `score_formula = PENDING`, `r = PENDING` - this note does not pin either; it supplies the evidence to pin them later.

Sources (re-fetched and read end to end 2026-09-30):
- `Informe1.tex` (Fondecyt 1191893 etapa 2019, Susana Marquez) - tracking + velocity, file id `1AsLrpUQMKXhhVfC47zu-58KSTaxk-LFB`.
- `Informe2.tex` (etapa Abril-Julio 2020) - automatic head finding, five filters, file id `1VCw9tY5qBoN9p-jAL8aiJgZZjwjQ1G0X`.
- Drive inventory `SuzanaMarquezStuff/Analysis/Homescope` walked 2026-09-30.
- Our numbers: theta/r sweep + `CLUSTERS_OUTPUT.md`, `cv/pipeline` v0.2 (flow, angle, clusters, head_tracking, velocity; score = STUB).

## 1. Her five filters (verbatim from Informe 2, "Summary of filters")

| # | Filter | Value | What it does | Strictness direction |
|---|--------|-------|--------------|----------------------|
| 1 | `mincontourdist` | 50 px | Two contours closer than this merge into one shape before ellipse fitting | smaller = stricter, more/smaller contours |
| 2 | `areasmin` (code: `areamin`) | 5000 px^2 | Discard ellipses below this area (small motions, likely not heads) | larger = stricter |
| 3 | `difaxes` | 10 px | Discard ellipses whose axis lengths differ by less than this (circular = vortex) | larger = stricter |
| 4 | `dmin` | 20 px | Lower bound on center-of-mass distance for clustering across subtractions (also the half-overlap upper bound: dist < major semi-axis) | larger = include only faster movers |
| 5 | `errorMin` | 0.9 (R^2) | Linear fit per 3-point cluster; keep only if R^2 > errorMin (heads move straight) | larger = stricter; relax to catch turning heads |

Notes from the source:
- Preprocessing: crop, resize 40%, grayscale, GaussianBlur (21,21). Contours from SSIM subtraction over 4 consecutive frames (3 difference images), Otsu binarization, findContours, distance merge.
- Ellipse fit requires >= 6 contour points, then filters 2 and 3 apply.
- The report listing shows `errorMin=0,9;` (would be a tuple in Python); the text states 0.9 - treat 0.9 as the intended value.
- Informe 1 states she compared trackers: best results with KCF (index 2) or TLD (index 3); box seed `xmin=5, ymin=305, w=h=40`.

## 2. Stage-by-stage mapping to our pipeline

| Her stage (Informe 2) | Our stage (cv/pipeline v0.2) | Relationship |
|---|---|---|
| crop + resize 40% + gray + GaussianBlur(21,21) | config-pinned input prep | same purpose, different params (ours pinned) |
| SSIM subtraction across 4 frames (3 diffs) | Lucas-Kanade optical flow (frame pairs) | different primitives - change map vs motion field; both answer "what moved" |
| Otsu + findContours + merge (`mincontourdist`=50) | flow vectors sampled onto the grid | hers extracts blobs; ours samples a motion field |
| ellipse fit + `areamin`/`difaxes`/points>=6 | (no analog) | we have no geometry gate; these are candidates for score inputs, not adopted |
| cross-subtraction clustering, half-overlap, `dmin`=20 | lattice HK clustering with angular-coherence constraint, neighbor window `r` | the direct analog: `r` ~ linkage distance, `theta` ~ coherence gate |
| linear fit R^2 > 0.9 | angular-coherence threshold `theta` | same criterion (straight motion), different primitive (R^2 over 3 points vs per-cell angle spread) |
| heads -> tracking box (box side = fitted ellipse axis) | `head_tracking` stage | both produce per-frame positions from the detection stage |
| velocity: `scale`=105 px per 1000 um, 2-min time step, correction `100000/(2*scale*scale_percent)` | `velocity` stage | her formula is the unit convention to adopt when comparing velocities |

## 3. What her numbers give our open decisions

- **theta** - `errorMin` is the same question we ask with theta: is this region's motion straight? Hers answers it per 3-point cluster with R^2; ours answers it per cell with angle spread. Her value 0.9 is a prior, not a transferable number (different primitive).
- **r** - `mincontourdist`=50 and `dmin`=20 are her linkage scales in pixels at 40% resize. They bracket what counts as "nearby" on this footage class. Converting to physical units: 50 px at 40% resize = 125 original px = 125/105 * 1000 um ~ 1.19 mm; `dmin` 20 px -> 50 orig px ~ 476 um. Caveat: `scale`=105 px per 1000 um is the value in Informe 1's velocity code for that sequence; each Homescope run must read its own `info.dat` + scale before pinning r in physical units.
- **theta 0.1 vs 0.2** - the sweep (r=1: theta 0.1 -> 3 clusters, theta 0.2 -> 1 cluster; r=0 singletons; r>=2 saturates) has no ground truth yet. Her `errorMin` shows the decision axis she used: straightness. Our fixture below supplies the ground truth her filter was standing in for.
- **score formula** - her `areamin` and `difaxes` show she scored regions on size and shape. Our score stub can draw on the same ingredients (cluster size, coherence margin, velocity stability); nothing adopted here, score stays PENDING.

## 4. Validation fixture plan (Homescope)

Inventory per run (`Analysis/Homescope/video1` and `video2`), from the 2026-09-30 folder walk:
- `Tracking3HS.ipynb` (124 KB video1, edited Jun 2024; 129 KB video2, Jul 2020 original) - her tracking notebook.
- `data1.3.dat` / `data1.6.dat` (50 B each) - flagged inference: seed box / initial ROI. Not confirmed until loaded.
- `data.npz` (456 B each) - flagged inference: per-frame tracked box centers (matches Informe 1's `np.savez('data', Data)` convention). Not confirmed until loaded.
- `output.avi` (400 / 367 KB) - rendered tracking visualization.
- video1 extras: `image0008.jpg` sample frame (4.1 MB, Feb 2020), `pictures/` frame sets, `checkpoints/`.

Steps:
1. Open `data1.3.dat` + `data.npz` and confirm semantics (seed box, center series). First step because the whole fixture's value hangs on it.
2. Pull a 1-2 minute clip of frames from `video1/pictures/` (scope per CV-lane quest: not the 40 GB runs).
3. Run our pinned `cv/pipeline` on those frames: flow -> angle -> clusters across a (theta, r) grid including the CLUSTERS_OUTPUT cases.
4. Diff: our per-frame head position(s) vs her `data.npz` centers - mean/p95 pixel error per frame; our seed behavior vs `data1.3.dat`; visual cross-check against `output.avi`.
5. Decision rule for theta/r: pick the (theta, r) whose trajectories minimize the npz diff, with the her-filter priors (straightness gate, ~mm-scale linkage) as tie-breakers. This turns CLUSTERS_OUTPUT's side-by-side panels into a pinned choice.
6. Score formula: candidate score validated when its value is stable across the passing runs and monotone against the npz error; then flip `score_formula` and `r` in the README convention from PENDING in their own commits.
7. Record `pipeline_version`, the exact frame window, and the per-run scale from `info.dat` alongside the result (README convention).

Acceptance criteria: reproducible from repo on a clean checkout; npz diff reported with numbers, not vibes; no change to frozen surfaces (nothing on-chain, program untouched).

## 5. Honest gaps

- `.dat` / `.npz` contents are inference from size + Informe 1's save convention until step 1 opens them. **Update 2026-09-30 (CE_Player run): video1 `data.npz` opened byte-level - confirmed 456 B, `arr_0`, shape (12,2), float64, range [158.33, 938.5], 40%-space centers. The inference held for video1.**
- Her filters were tuned on Nikon/Homescope footage at 40% resize with SSIM+contour primitives; our grid config differs - priors, not drop-in values.
- The mapping in section 2 is analogical (marked), not equivalence; ellipse-stage filters have no counterpart in our pipeline.
- `Tracking3HS.ipynb` not opened this pass - inventory only; it may contain her per-run scale and extra params worth folding into step 1.
- Informe 1 covers both microscopes; Homescope-specific scale must come from each run's `info.dat`, not assumed from `scale`=105.
