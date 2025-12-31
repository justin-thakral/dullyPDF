# Sandbox PDF Catalog

This folder stores **classified copies** of input PDFs used by the sandbox.

- `manifest.json` lists repo-relative PDFs grouped into `native` and `scanned` buckets.
- Copies are stored under `native/` and `scanned/`, subdivided into `hippa/`, `consent/`, and `intake/`.
- Classification is driven by the text-layer heuristic in `backend/fieldDetecting/sandbox/combinedSrc/text_layer.py`.
- `manifest.json` is a snapshot; update it manually after re-sorting PDFs (there is no auto-regenerator yet).
Recommended classifier:
```
python3 -m backend.fieldDetecting.sandbox.tools.sort_pdfs --pdfs-dir backend/fieldDetecting/pdfs
```

If you move PDFs, update:
- references in docs/scripts
- any ML metadata that stores absolute source paths
