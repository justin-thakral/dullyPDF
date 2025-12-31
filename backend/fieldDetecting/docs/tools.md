# Sandbox tools

This file documents the helper scripts in `backend/fieldDetecting/sandbox/tools/`.
These scripts are intended for local maintenance and organization.

## sort_pdfs.py

Classifies PDFs into `native/` and `scanned/` groups using the text-layer heuristic.
It preserves the relative path under the source root to avoid filename collisions.

```bash
python3 -m backend.fieldDetecting.sandbox.tools.sort_pdfs --pdfs-dir backend/fieldDetecting/pdfs
```

Key options:
- `--pdfs-dir`: root folder containing PDFs to classify.
- `--pdfs-output-root`: destination root for `native/` + `scanned/` (default: `backend/fieldDetecting/pdfs`).
- `--forms-dir`: optional root of existing fillable PDFs to classify separately.
- `--forms-output-root`: destination root for forms classification (default: `backend/fieldDetecting/forms`).
- `--mode move|copy`: default `move`.
- `--workers`: override thread count (or use `SANDBOX_SORT_WORKERS`).

Notes:
- Uses `sandbox/combinedSrc/text_layer.py` heuristics for classification.
- Does not regenerate `backend/fieldDetecting/pdfs/manifest.json` automatically.
- When `--forms-dir` is provided, outputs land in `forms/native/` and `forms/scanned/`.

## migrate_ml_pdfs.py

Moves the ML corpus PDFs into the standard `pdfs/native` + `pdfs/scanned` layout.
It infers a category (`hippa`, `consent`, `intake`) from the path and preserves subfolders.

```bash
python3 -m backend.fieldDetecting.sandbox.tools.migrate_ml_pdfs
```

Key options:
- `--ml-root`: source dataset root (default `backend/fieldDetecting/sandbox/ML/data/raw/pdfs`).
- `--pdfs-root`: destination root (default `backend/fieldDetecting/pdfs`).
- `--mode move|copy`: default `move`.

## migrate_analysis_artifacts.py

Migrates legacy `outputArtifacts/analysis_*` runs into the current layout:

- JSON -> `outputArtifacts/json/analysis_*`
- Overlays -> `outputArtifacts/overlays/analysis_*`
- Raw artifacts -> `outputArtifacts/overlays/analysis_*/raw`

```bash
python3 -m backend.fieldDetecting.sandbox.tools.migrate_analysis_artifacts --dry-run
python3 -m backend.fieldDetecting.sandbox.tools.migrate_analysis_artifacts
```

Key options:
- `--root`: sandbox root (default `backend`).
- `--mode move|copy`: default `move`.
- `--dry-run`: print actions without moving.

## artifactManager.py

Removes temp-prefixed artifacts under `outputArtifacts/` and `forms/`.
Also prunes any empty directories left behind.

```bash
python3 -m backend.fieldDetecting.sandbox.tools.artifactManager --dry-run
python3 -m backend.fieldDetecting.sandbox.tools.artifactManager
```

Key options:
- `--root`: sandbox root (default `backend`).
- `--prefix`: filename prefix to remove (default `temp`).
- `--dry-run`: print actions without deleting.

## batch_review.py

Batch-runs the pipeline on a directory of PDFs and writes a report (JSON + CSV).
Overlays can be generated for all PDFs or just those flagged by heuristics.

```bash
python3 -m backend.fieldDetecting.sandbox.tools.batch_review --pdfs-dir backend/fieldDetecting/pdfs/native/hippa --overlays issues
```

Key options:
- `--pdfs-dir`: root folder to scan for PDFs.
- `--output-dir`: root output folder for `json/` + `overlays/`.
- `--pipeline`: `auto|native|scanned` (default `auto`).
- `--pattern`: substring filter for filenames.
- `--max`: limit number of PDFs processed.
- `--offset`: skip the first N PDFs in the sorted list.
- `--overlays`: `none|all|issues` (default `issues`).
- `--save-json`: write per-PDF candidates/fields JSON.
