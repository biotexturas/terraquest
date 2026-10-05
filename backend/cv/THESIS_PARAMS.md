# Thesis parameters — Bravo 2019 reference extraction

Source: Pablo Bravo, June 2019, "Dynamics of swarming clusters in Paenibacillus" — Informe de Práctica de Licenciatura, Pontificia Universidad Católica de Chile (Instituto de Física), supervised by Juan. 32 pp.
Delivered by b0 to the coordination hub 2026-09-29 11:27Z (Google Drive working link, verified open).
Extracted by b.2 2026-09-29 (full-document pass). Every value carries its printed page cite; anything not in the document is marked NOT STATED and stays open rather than inferred.

## 1. Headline finding: no single "score formula" in the thesis
The thesis defines SEPARATE cluster metrics. The only quantity explicitly called a cost function is the snake-head tracking criterion g = e^A / d (p. 14). The on-chain u16 score is our composition of one of these metrics — Juan's decision 2 (CV output shape) now has a bounded, cited candidate list.

## 2. Score-metric candidates (all thesis-sourced)
| # | metric | definition | page |
|---|---|---|---|
| 1 | cluster size A | number of lattice cells in cluster (p.d.u.; cells reported 10 px² homogeneous / 5 px² localized, as printed) | p. 22 |
| 2 | kinetic energy E | E = ∫ (vx²+vy²)/2 dS | p. 4 Eq.(2) |
| 3 | energy density e | e = E/A (words, unnumbered); equilibrium e_eq ≈ 700 p.d.u. reported | p. 22 / p. 23 |
| 4 | enstrophy Ω | Ω = ∫ w²/2 dS (discretized vorticity Eq.(13) p. 21) | p. 6 Eq.(3) |
| 5 | cluster spin W_C | W_C = Σ w_i over cluster cells; >0 CW, <0 CCW; no numeric range stated | p. 21 Eq.(14) |
| 6 | scaling Ω = e^α·E^β | β = 0.941±0.0004 (homogeneous), 0.998±0.0004 (point-like); α NOT STATED | p. 24 Eq.(15) |

## 3. Clustering parameters (modified Hoshen-Kopelman + angular coherence)
Membership (p. 13): |r_ij| <= r_min AND |θ_i − θ_j| < θ_min (strictly less than).
- Structure-identification run (p. 18): r_min = 3 px, θ_min = 0.1, LK resolution 10, v_min = 0.2 px, v_max = 500 px.
- Time-evolution runs (pp. 22-23): clustering distance 3 px, angular similarity 0.2 rad, LK resolution 10 px (homogeneous) / 5 px (localized), velocity range {3 : 500 px/min}.
- Appendix picks top-20 clusters: big_clusters(FRHK, 20) hard-coded.

OPEN — UNIT MAPPING: thesis reports r in px, but float_range_hk(A, r, theta) uses r as an array-index window over the angle matrix (grid spacing = lk_res). The text does not state the px-to-cell conversion. Our real-footage run: r=0 cells = degenerate self-only window; r=2 cells = full-grid saturation on this footage. r pin stays PENDING until units align — do not silently substitute r=3.
Theta candidates are concrete now: 0.1 (structure ID) and 0.2 rad (dynamics); compare our demo config against both before the next run.

## 4. Optical flow / Lucas-Kanade (appendix p. 30)
- OpenCV pyramidal LK: winSize=(10,10), maxLevel=10, criteria EPS|COUNT (10 iterations, eps 0.03).
- Grid: for i in range(0, w, res) x for j in range(0, h, res); V shape (h/res, w/res).
- Velocity accept: vmin <= mag <= vmax; angle = arctan2(...); NaN outside.
- Two angle matrices denoised by circular mean: arctan2(sin A + sin B, cos A + cos B); zeros -> NaN.

## 5. Head tracking / SSIM (appendix p. 29; method pp. 14, 18)
- Preprocess: GaussianBlur((21,21), 0).
- SSIM full=True (thesis Eq. 9 p. 14; text specifies 11x11 Gaussian window; c1/c2 NOT STATED).
- Diff x255 -> uint8 -> THRESH_BINARY_INV | THRESH_OTSU (no fixed numeric SSIM threshold anywhere).
- Contours: RETR_EXTERNAL, CHAIN_APPROX_SIMPLE; scoring only when len(cnts) < 45.
- Criterion: exp(area) / squared_distance to previous head (thesis writes d = distance; script uses squared — divergence recorded as-is); prev head init (0,0); select argmax.
- Prev-head update only if area > 0.3; marker circle radius 15.
- Other printed constants: vortex detection reliable above ~100 px (p. 18); N = {20,50,100,200} homogeneous, N = 20 localized (p. 22); localized mean cluster size oscillates near A = 115 p.d.u. (p. 23).

## 6. Effect on the README convention lines
- pipeline_version = cv-pipeline v0.2 unchanged.
- score_formula = PENDING stays true (Juan picks metric + u16 mapping) but is no longer blocked on missing input — candidates in section 2 are bounded and cited.
- r pin stays PENDING per section 3 unit-mapping question.

## 7. Theta comparison sweep results (2026-09-29, CI run 36579309972)
Recorded in cv/realrun/THETA_SWEEP.md (committed by the run). 8 runs (theta {0.1, 0.2} x r_cells {0,1,2,3}) on the real Saturns frames, demo grid 50x66 cells (FlowParams res=50), n_clusters=20:
- r_cells = 0: DEGENERATE at BOTH thetas — 20 singleton clusters (top_sizes all 1). Theta has no effect without neighbors.
- r_cells >= 1: full-grid saturation at both thetas — largest cluster 3297-3299 of 3299 labeled cells.
- theta 0.1 vs 0.2 differs ONLY at r_cells = 1: 0.1 -> 3 clusters (3297, 1, 1); 0.2 -> 1 cluster (3299). At r_cells >= 2 the two thetas are identical on this footage.
- Reading: window r is the dominant lever; theta is secondary and only discriminates at the saturation edge. The multi-cluster regime the thesis describes does not exist at 50 px cells on this footage — the section 3 unit mapping is the blocking question for the r pin, not the theta choice.
- score_formula stays PENDING (Juan's metric pick); this run does not touch score.py or any u16.
