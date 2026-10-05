# TerraQuest CV pipeline (lane two) - v0.2 stage bodies

Clean rebuild of the thesis-appendix CV pipeline (Pablo Bravo 2019): Lucas-Kanade optical flow, modified Hoshen-Kopelman clustering with angular-coherence constraint, SSIM-based head tracking - plus the Tracking3HS velocity reference.

## README convention (score formula + pipeline version, per Juan)

- pipeline_version: `cv-pipeline v0.2` (stage bodies landed: flow, angle, clusters incl. big_work2 end-to-end, head tracking; synthetic test suite at `cv/tests/test_pipeline.py`)
- score_formula: **PENDING** - not present in any source notebook; awaiting thesis PDF (primary, asked of b0) or b0's written pipeline spec (fallback). No on-chain u16 score gets minted until this line is pinned.
- source_extraction: artifact `D0437B3E` (cv-notebook-pipeline-extraction), from Juan's public Drive folder Paenibacillus_tracking, CI nb-extract run 36525307763, extraction commit ac503d9
- extracted_sources: `cv/head_tracking.md`, `cv/optical_flow.md`, `cv/clusters.md`, `cv/tracking3hs.md`

## Modules (`cv/pipeline/`)

- `config.py` - all pinned parameters, one place, versioned
- `flow.py` - **v0.2**: grid LK optical flow + field assembly (source dtype bug fixed)
- `angle.py` - **v0.2**: angle/magnitude split, ang_dif, circular-mean denoise
- `clusters.py` - **v0.2**: HK labeling with angular coherence (cvals fix), top-N (`~n:` fix), `big_work2` end-to-end wired (frame loading -> dual flow -> denoise -> HK -> top-N -> 0->NaN)
- `head_tracking.py` - **v0.2**: SSIM diff, Otsu, exp(area)/dist^2 contour criterion, prev_centroid threaded by caller
- `velocity.py` - stage: Tracking3HS reference (README-unmapped in source; role pending Juan/b0)
- `score.py` - score aggregation to u16 (**STUB**, see score_formula above)

## Bug fixes vs the notebooks (fix, not port)

1. Flow-matrix write `V[i,j] = np.array(v[1], v[0])` passed `v[0]` as dtype - corrected to an explicit 2-vector store.
2. HK label merge referenced an undefined name (`cvals` vs loop var `cvalues`) - corrected.
3. Top-N cluster slice `unique[~n:]` (bitwise-not on an int) - corrected to `unique[-n:]`.
4. Deprecated/removed APIs: `skimage.measure.compare_ssim` moves to `skimage.metrics.structural_similarity`; legacy `cv2.TrackerTLD_create` flagged in `velocity.py`.
5. Hardcoded absolute paths (`/home/juan/...`, `./pictures*`) parameterized as input dirs.

## Parameters: pinned vs pending

- LK flow: res=50, win=15, levels=4 (demo values; Pablo's own 10/10 divergence recorded in source)
- Head tracking: Gaussian blur 101, Otsu, criterion exp(0.001*area)/dist^2
- Clusters: theta=0.1, vmin=1, vmax=20000, N=20 - **r=0 in the demo is suspicious (self-only neighbors; tests confirm it degenerates to per-cell labels); pin r/theta from the thesis before trusting cluster output**
- score formula + u16 aggregation: **PENDING** (see above)

## Known float edge (documented in tests)

`denoise` maps an exact-zero resultant to NaN per the source quirk, but exact antipodal angles (0, pi) leave a sin(pi)~1e-16 residual so arctan2 returns ~pi/2 instead. Matches source arithmetic; measure-zero in real data.

## Tests

`python cv/tests/test_pipeline.py` (or pytest) - synthetic-data suite covering grid/assemble, angle masking, circular helpers, HK labeling, and top-N selection. Requires numpy + opencv-python; no footage needed.

## Status

v0.2: all four core stage bodies landed and unit-tested on synthetic data. Remaining before the convention closes: (1) score formula pin from thesis/b0, (2) r/theta thesis pin, (3) run on the 1-2 min clip with the version log above.
