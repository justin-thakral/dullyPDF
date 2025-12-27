# ML Field Detector Plan (Sandbox)

This document is a **step-by-step plan** to build a **machine learning detector** that finds fillable-form fields directly from rendered PDF pages and plugs into the existing `backend` pipeline.

The focus is high-recall detection of:
- **Checkboxes** (including dense grids / Y-N columns)
- **Underline-based text fields** (the most common “write here” affordance)
- **Boxed text fields** (rectangles)
- Optionally: **table entry cells** (structured grids) and **signature/date underlines**

The plan is designed so a new engineer can follow it and succeed without guessing.

---

## 0) What “success” means

### Primary success criteria
1) **Recall-first**: for a given form page, the detector should find essentially all real input fields.
2) **No “O as checkbox”**: eliminate the common false positive where the letter “O” (or “0”) looks like a square checkbox in binarized scans.
3) **Table/grid sanity**: table borders and section headers should **not** become text fields.
4) **Drop-in integration**: ML outputs should map to the existing candidate schema so we can reuse:
   - `rect_builder.py` (underline → typing rectangle)
   - `rename_resolver.py` (naming/filtering via overlay pass)
   - overlays and debug tooling

### Practical target metrics (per page)
- Checkbox recall: **≥ 99%** on checkbox-heavy pages.
- Underline recall: **≥ 99%** on pages dominated by underlines.
- Precision can be lower (we can filter), but aim for:
  - Checkbox precision: **≥ 95%**
  - Underline precision: **≥ 90%**

If precision is lower, we add deterministic post-filters (see §7).

---

## 1) Decide output contract (match the current pipeline)

The existing sandbox pipeline works around a consistent JSON contract. Keep it.

### Candidate schema (target)
For each rendered page:
- `lineCandidates`: underline-like bboxes (originTop, points)
- `checkboxCandidates`: square bboxes (originTop, points)
- `boxCandidates`: rectangles (originTop, points)

Each candidate should include:
- `id`: unique, stable string (e.g., `ml-line-<page>-<n>`)
- `bbox`: `[x1, y1, x2, y2]` in **points** (originTop)
- Optional: `detector`: string tag (e.g., `ml_yolo`)
- Optional: `score`: model confidence (0–1)

Why this contract:
- `rect_builder.py` already knows how to turn underline candidates into a “typing rectangle”.
- The OpenAI/heuristic resolvers already understand candidate IDs and can dedupe/merge.

---

## 2) Choose the ML approach (recommended: tiled object detection)

### Why object detection (not OCR-first)
We want fields, not text. OCR has two major failure modes:
- missing text layer on scanned PDFs
- dense layouts causing misalignment and “header classified as field”

Object detection on the rendered image avoids both.

### Recommended baseline model
Use a modern, production-friendly detector with strong small-object support:

**Option A (recommended first): YOLOv8 (Ultralytics)**
- Pros: easy training, fast inference, strong ecosystem
- Cons: needs careful handling for tiny checkboxes and long thin underlines

**Option B: Detectron2 Faster R-CNN / RetinaNet**
- Pros: strong small-object performance with FPN
- Cons: heavier setup

For this project phase, start with **YOLOv8** and only switch if results plateau.

### Critical design detail: tiling
Your pages are ~`4245 x 5493` px at 500 DPI. Training/inference at full resolution is impractical.

Use **tiling with overlap**:
- tile size: `1024` or `1280`
- stride: `0.75 * tile_size` (e.g., 768 for 1024 tiles)
- merge predictions with NMS in global coordinates

This is the single biggest factor for small checkbox recall.

---

## 3) Define labels/classes (taxonomy)

Start with 3 classes. Expand later.

### Minimal classes (v1)
1) `checkbox`  
2) `underline` (text-entry underline)  
3) `textbox` (boxed rectangle entry field)

### Optional classes (v2)
4) `signature_underline` (if you want different rect rules)  
5) `table_cell` (entry cells inside tables)  
6) `radio` (if you encounter circles)  

Recommendation:
- Start with v1. Most forms will be solved by checkbox + underline.
- Add v2 only when you have labeled data and you see recurring errors.

---

## 4) Build the dataset (most important step)

### 4.1 Source PDFs to include
Collect a training corpus of PDFs representing your target distribution:
- medical intake forms (checkbox-heavy)
- insurance forms (underline-heavy)
- forms with tables/grids
- scanned + digital hybrids

Minimum viable dataset:
- **50 PDFs** (or fewer if each has many pages/fields)
- **500–2,000 pages** rendered (more is better)

### 4.2 Rendering pipeline (consistent + reproducible)
Render with the same code path you ship:
- `backend/combinedSrc/render_pdf.py` renders at 500 DPI today.

For ML training, you can optionally render at **400 DPI** to reduce compute while preserving checkbox detail.

Store:
- `images/<pdf_name>/page_<n>.png`
- `meta/<pdf_name>/page_<n>.json` with:
  - page index
  - page width/height pts
  - rotation
  - render scale

### 4.3 Annotation tool (pick one and standardize)
Choose one:
- **CVAT** (best for teams; exports COCO)
- **Label Studio** (fine; needs COCO conversion)
- **Roboflow** (fast; may require data export controls)

Recommendation: **CVAT + COCO export**.

### 4.4 Annotation guidelines (to avoid “O checkbox” and header pollution)

This is where your current OpenCV learnings directly apply.

#### Checkbox annotation rules
Annotate:
- the **outer square** bbox tightly around the checkbox border

Do NOT annotate:
- legend squares in headers (e.g., “Past Condition / Ongoing Condition” color keys)
- glyphs like the letter **O**, the digit **0**, or small rounded boxes inside text

How to consistently avoid “O checkbox”:
- Include pages with large bold headers containing “O” (e.g., “HOSPITALIZATIONS”) and ensure:
  - background has many “O” instances
  - only real checkboxes are labeled
This forces the model to learn “O is not a checkbox” from negative examples.

#### Underline annotation rules
Annotate:
- the underline segment that indicates where a user writes
- bbox should be tight to the underline thickness (don’t include label text)

Do NOT annotate:
- page-wide divider rules
- table grid borders (horizontal lines inside tables)
- section header borders

#### Textbox annotation rules
Annotate:
- rectangles intended for writing (blank boxes)

Do NOT annotate:
- decorative header boxes (e.g., rounded gray section headers)
- table header cells that already contain printed text

### 4.5 Use tiling during labeling or during preprocessing
Two approaches:

**Approach A: Label full pages**
- Pros: human-friendly
- Cons: training needs tiling conversion step

**Approach B: Pre-tile pages and label tiles**
- Pros: no conversion needed
- Cons: labeling is more annoying

Recommendation: **Label full pages**, then generate tiled COCO for training.

---

## 5) Data prep pipeline (COCO → tiled YOLO)

### 5.1 Keep a single “source of truth”
Store annotations in COCO using full-page coordinates.

Example structure:
- `backend/ML/data/raw/images/...`
- `backend/ML/data/raw/annotations/train.json`
- `backend/ML/data/raw/annotations/val.json`

### 5.2 Generate tiled training set
Write a deterministic script (proposed filename):
- `backend/ML/prepare_tiled_dataset.py`

Algorithm:
1) Load each page image and its COCO annotations.
2) Generate overlapping tiles.
3) For each tile:
   - include any GT box whose center lies inside the tile
   - clip bbox to tile bounds
   - drop bboxes smaller than a minimum size after clipping (e.g., `< 4x4 px`)
4) Save:
   - `backend/ML/data/tiles/images/<page>__x<tileX>_y<tileY>.png`
   - `backend/ML/data/tiles/labels/<same>.txt` in YOLO format

### 5.3 Train/val split rules (avoid leakage)
Split by **PDF**, not by page:
- `train`: 80%
- `val`: 10%
- `test`: 10%

Otherwise the model memorizes repeated templates and looks artificially perfect.

---

## 6) Training recipe (YOLOv8)

### 6.1 Environment setup
Use a dedicated venv or conda env.

Recommended packages:
- `ultralytics`
- `opencv-python`
- `numpy`
- `pyyaml`

If you use GPU:
- install `torch` matching your CUDA version

### 6.2 Training config (starting point)
Key training settings for tiny checkboxes + long underlines:
- `imgsz`: `1280` (or `1024` if VRAM limited)
- `batch`: as large as fits (start at 16 for 12GB VRAM, adjust)
- `epochs`: 100–200
- `optimizer`: SGD or AdamW (Ultralytics default is fine)
- augmentations:
  - small rotation: ±1.5°
  - mild perspective
  - brightness/contrast jitter
  - gaussian noise
  - blur (simulate scan)
  - JPEG compression artifacts

Avoid heavy rotation; forms are mostly upright.

### 6.3 Class imbalance handling
Checkboxes may vastly outnumber underlines or vice versa depending on forms.

Mitigation options:
- oversample pages with rare classes
- ensure val set includes all classes
- consider focal loss (if supported) or class weights

### 6.4 Evaluation during training
Track:
- per-class recall at low thresholds (e.g., conf=0.10)
- per-class precision
- mAP50 for sanity

For this project, **recall is king** because downstream filters can remove false positives.

---

## 7) Post-processing (make the ML output “production safe”)

Even with ML, add deterministic guardrails that encode what we learned from OpenCV failures.

### 7.1 Dedupe (global NMS)
After merging tile predictions, run NMS per class in full-page coordinates.
- Use IoU threshold ~0.5 for checkboxes
- Use IoU threshold ~0.7 for underlines/textboxes (since overlaps are common)

### 7.2 Checkbox “O” safety filter (recommended)
Even if the model is good, keep a cheap secondary filter to stop regressions:
- for each predicted checkbox bbox:
  - crop the region
  - binarize
  - compute hole-area ratio (same concept used in `detect_geometry.py`)
  - reject if hole ratio < ~0.36 (tune on validation)

This turns a catastrophic false positive class into a bounded risk.

### 7.3 Underline divider-rule filter
Reject underline candidates that are “too long” for a field:
- if `length_px >= 0.92 * page_width_px`: likely a divider rule

### 7.4 Table/grid filter (avoid border lines)
If you detect table cells separately, treat those as the true fields.
If you do NOT detect table cells:
- infer table regions from dense line grids and suppress underline predictions inside them.

---

## 8) Inference pipeline integration (into `backend`)

### 8.1 Add an ML detector module
Proposed module:
- `backend/ML/ml_detector.py`

Responsibilities:
1) Load model weights once (singleton).
2) Run tiled inference on `page["image"]`.
3) Apply post-processing and filters.
4) Return candidates in the existing schema:
   - `lineCandidates`, `checkboxCandidates`, `boxCandidates`

### 8.2 Convert pixel bboxes → point bboxes
Reuse existing coordinate utilities:
- `backend/combinedSrc/coords.py` (`px_to_pts`, `PageBox`)

Store both if useful:
- `bboxPx` for debugging
- `bbox` for pipeline consumption

### 8.3 Hook it into `detect_geometry.detect_geometry`
Current pipeline:
- `render_pdf_to_images` → `detect_geometry` → `assemble_candidates` → resolver

Integrate with an env flag:
- `SANDBOX_USE_ML_DETECTOR=1`

Implementation strategy:
- Run ML detector per page.
- Union results with OpenCV results for high recall (at least initially).
- Add `detector` tags (`ml_*` vs `opencv_*`) and IoU-dedupe.

Why union-first:
- You can gradually trust ML more as validation improves.
- You avoid regressions on edge cases you haven’t labeled yet.

### 8.4 Keep debug overlays
The current overlay tool draws candidates and final rects:
- `backend/debug/debug_overlay.py`

Continue writing (under the output root's `overlays/` folder):
- `overlays/temp<first5><last5>_page_<n>.png` (debug overlays)
- `overlays/temp<first5><last5>_openai/page_<n>.png` (OpenAI rename overlays)

Add color-coding by detector source if needed (future improvement).

---

## 9) Validation workflow (how you know it works)

### 9.1 Golden PDFs
Pick a small set of “golden” PDFs (including `backend/pdfs/scanned/medical-history-intake-form.pdf`) and maintain:
- expected count of fields per page (rough)
- known failure patterns:
  - “O checkbox” false positives
  - missed “First Name ____” underlines
  - headers detected as fields

### 9.2 Automated checks to add
Create a lightweight validator script:
- `backend/ML/validate_ml_outputs.py`

Checks:
- For each golden page:
  - ensure at least N underlines detected
  - ensure “O checkbox” count == 0 in known header bboxes
  - ensure checkboxes are within reasonable size bounds

### 9.3 Human QA loop
For each training iteration:
1) run `debug/test_rects.py` to produce overlays
2) scan overlays for:
   - missed underlines
   - table border noise
   - “O” false checkboxes
3) add those pages to labeled set (“hard examples”)
4) retrain

This loop converges quickly for form detection.

---

## 10) Data scaling strategy (how to get “perfect”)

The fastest path to “perfect” is not exotic models; it’s **hard-example mining**.

### 10.1 Hard example mining
After training a baseline:
1) Run inference over an unlabeled PDF corpus.
2) Find pages where:
   - underlines detected == 0 but OpenCV found many
   - checkbox detections exist inside large text areas
   - predicted boxes cluster around headers
3) Label only those pages.
4) Retrain.

### 10.2 Synthetic augmentation (optional but powerful)
Generate synthetic pages that contain:
- many “O” glyphs of different fonts/sizes
- checkbox-like squares near text
- broken checkbox borders
- faint underlines

Use these to teach the model invariances quickly.

---

## 11) GPU training notes (practical)

### Recommended hardware
- 1 GPU with 12–24GB VRAM is plenty for YOLOv8 with 1024–1280 tiles.

### Common gotchas
- If checkbox recall is low:
  - increase tile resolution (`imgsz=1280`)
  - reduce stride (more overlap)
  - add more checkbox-heavy pages
- If underlines are missed:
  - add more underline-heavy pages
  - consider a segmentation model for underlines (YOLOv8-seg) as v2

---

## 12) Suggested milestone plan (what to do first)

### Milestone 1 (2–3 days): dataset + baseline model
1) Pick 10 PDFs (including the medical intake PDF).
2) Render pages + annotate full pages (checkbox/underline/textbox).
3) Build tiling dataset script.
4) Train YOLOv8 baseline.
5) Evaluate on the medical intake PDF overlays.

### Milestone 2 (1 week): hard-example mining + post-filters
1) Run baseline on 100+ PDFs.
2) Collect failure pages and label them.
3) Add the “O hole-ratio” safety filter.
4) Add divider-rule + table-region suppression.

### Milestone 3 (ongoing): integrate + replace OpenCV gradually
1) Integrate ML detector behind `SANDBOX_USE_ML_DETECTOR`.
2) Union ML + OpenCV outputs, dedupe.
3) Once ML recall consistently beats OpenCV, disable OpenCV paths per class.

---

## 13) How this fits with OpenAI naming (recommended architecture)

Even with ML detection, keep OpenAI for what it’s best at:
- naming fields from nearby labels
- grouping fields into structured outputs
- mapping to DB variables

Architecture:
1) ML produces candidates (high recall).
2) The resolver (OpenAI or heuristic) assigns names/types.
3) Deterministic merges ensure no fields disappear if the model omits them.

This hybrid approach is resilient and production-friendly.
