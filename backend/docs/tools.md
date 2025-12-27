# Sandbox tools

This file documents the helper scripts in `backend/tools/`.
These scripts are intended for local maintenance and organization.

## sort_pdfs.py

Classifies PDFs into `native/` and `scanned/` groups using the text-layer heuristic.
It preserves the relative path under the source root to avoid filename collisions.

```bash
python3 -m backend.tools.sort_pdfs --pdfs-dir backend/pdfs
```

Key options:
- `--pdfs-dir`: root folder containing PDFs to classify.
- `--pdfs-output-root`: destination root for `native/` + `scanned/` (default: `backend/pdfs`).
- `--forms-dir`: optional root of existing fillable PDFs to classify separately.
- `--forms-output-root`: destination root for forms classification (default: `backend/forms`).
- `--mode move|copy`: default `move`.
- `--workers`: override thread count (or use `SANDBOX_SORT_WORKERS`).

Notes:
- Uses `combinedSrc/text_layer.py` heuristics for classification.
- Does not regenerate `backend/pdfs/manifest.json` automatically.
- When `--forms-dir` is provided, outputs land in `forms/native/` and `forms/scanned/`.

## migrate_ml_pdfs.py

Moves the ML corpus PDFs into the standard `pdfs/native` + `pdfs/scanned` layout.
It infers a category (`hippa`, `consent`, `intake`) from the path and preserves subfolders.

```bash
python3 -m backend.tools.migrate_ml_pdfs
```

Key options:
- `--ml-root`: source dataset root (default `backend/ML/data/raw/pdfs`).
- `--pdfs-root`: destination root (default `backend/pdfs`).
- `--mode move|copy`: default `move`.

## migrate_analysis_artifacts.py

Migrates legacy `outputArtifacts/analysis_*` runs into the current layout:

- JSON -> `outputArtifacts/json/analysis_*`
- Overlays -> `outputArtifacts/overlays/analysis_*`
- Raw artifacts -> `outputArtifacts/overlays/analysis_*/raw`

```bash
python3 -m backend.tools.migrate_analysis_artifacts --dry-run
python3 -m backend.tools.migrate_analysis_artifacts
```

Key options:
- `--root`: sandbox root (default `backend`).
- `--mode move|copy`: default `move`.
- `--dry-run`: print actions without moving.

## artifactManager.py

Removes temp-prefixed artifacts under `outputArtifacts/` and `forms/`.
Also prunes any empty directories left behind.

```bash
python3 -m backend.tools.artifactManager --dry-run
python3 -m backend.tools.artifactManager
```

Key options:
- `--root`: sandbox root (default `backend`).
- `--prefix`: filename prefix to remove (default `temp`).
- `--dry-run`: print actions without deleting.
