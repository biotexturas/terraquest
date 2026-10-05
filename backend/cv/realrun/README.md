# cv/realrun - real-data validation runs

Runs the CE_Player-derived pipeline on Susana Marquez's Homescope video1
frames and validates the output against her TLD ground truth.

pipeline_version = cv-pipeline v0.2 + ce_player_video1 v0.1 (CE_Player params verbatim)
score_formula = PENDING (this run validates tracked centers, not the u16 score)
delta_t = 2 minutes per frame (Informe 1 verbatim; notebook factor 100000/(2*scale*scale_percent), the 2 = time step)
frame_order = sorted(glob('./pictures/*.jpg')) -> image0009..image0020, 12 frames

## Files

- `ce_player_video1.py` - standalone runner (opencv + numpy only). Intentionally
  does not import `cv/pipeline`: the Drive frames are not present in CI test
  jobs, so the real-data runner must stay rerunnable anywhere the files exist.
- `ce_player_video1_results.json` - machine-readable metrics, written by the
  runner and committed back by CI.
- `ce_player_video1_run_log.txt` - full evidence log (byte sizes, npz keys,
  coordinate-space decision, per-pair and per-frame numbers) committed by CI.
- `CE_PLAYER_VIDEO1_RUN.md` - human report with every number and honest
  observations.
- `../../.github/workflows/realrun-video1.yml` - CI pipeline that fetches the
  inputs, runs the metrics, and commits the results.

## Run locally

```bash
python cv/realrun/ce_player_video1.py --frames /path/to/pictures --npz /path/to/data.npz
```

## Run in CI

Actions -> realrun-video1 -> Run workflow. The workflow also auto-runs on any
push touching `cv/realrun/`. CI downloads the 12 frames and `data.npz` from
Susana's shared Drive, runs both stages, and commits the results JSON and run
log back to this directory. CI-authored commits use GITHUB_TOKEN, so they do
not retrigger workflows (no loops).

## Inputs (Susana's Drive, anyone-with-link)

- video1 folder: `1Nw09PzQABh6ygrukCxWY3Ooq8I1lL6oT` (parent Homescope
  `1k4GKVUi3itOwtKse3hMNNHx7dEgZLY5f`)
- data.npz: `1CuCRxkmLKnZDc84r7VTZw87s9ukcNiWj` - 456 bytes, `arr_0`
  shape (12, 2) float64 (verified byte-level 2026-09-30)
- pictures folder: `1F3Mz9BQOn9jdLLktGCA-3-N057yPqR2E`
- the 12 frame IDs live in the workflow file (single source of truth)

## Metrics

- blob vs TLD: per-frame Euclidean error for frames 1..11, mean and max (px)
- LK: per-pair mean displacement magnitude, 11 pairs (0.5 px FB rejection)
- velocity: `v = disp_px * 100000/(2*1400*40)`; reference is Susana's TLD run
  of 74.1 +/- 12.2 um/min
