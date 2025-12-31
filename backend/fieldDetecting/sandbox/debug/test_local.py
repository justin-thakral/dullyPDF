import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ..combinedSrc.config import get_logger
from ..combinedSrc.output_layout import ensure_output_layout, temp_prefix_from_pdf
from ..combinedSrc.rename_resolver import run_openai_rename_pipeline
from ..combinedSrc.pipeline_router import run_pipeline as run_pipeline_router

logger = get_logger(__name__)


def run_pipeline(
    pdf_path: Path,
    output_root: Path | None,
    *,
    pipeline: str = "auto",
    openai: bool = False,
) -> Dict[str, Any]:
    pdf_bytes = pdf_path.read_bytes()
    session_id = f"local-{datetime.now(tz=timezone.utc).timestamp()}"

    pipeline_run = run_pipeline_router(
        pdf_bytes,
        session_id=session_id,
        source_pdf=pdf_path.name,
        pipeline=pipeline,
    )
    result = pipeline_run.result

    rendered_pages = pipeline_run.artifacts.rendered_pages
    candidates = pipeline_run.artifacts.candidates

    if output_root is None:
        output_root = Path("backend/fieldDetecting/outputArtifacts")
    layout = ensure_output_layout(output_root)
    prefix = temp_prefix_from_pdf(pdf_path)
    canonical_fields_path = layout.json_dir / f"{prefix}_fields.json"
    candidates_path = layout.json_dir / f"{prefix}_candidates.json"

    candidates_path.write_text(json.dumps({"candidates": candidates}, indent=2))
    logger.info("Wrote %s", candidates_path)

    canonical_fields_path.write_text(json.dumps(result, indent=2))
    logger.info("Wrote output JSON to %s", canonical_fields_path)

    if openai:
        rename_dir = layout.overlays_dir / f"{prefix}_openai"
        rename_result, renamed_fields = run_openai_rename_pipeline(
            rendered_pages,
            candidates,
            result.get("fields", []),
            output_dir=rename_dir,
        )
        rename_path = layout.json_dir / f"{prefix}_renames.json"
        rename_path.write_text(json.dumps(rename_result, indent=2))
        logger.info("Wrote rename output JSON to %s", rename_path)
        renamed_path = layout.json_dir / f"{prefix}_fields_renamed.json"
        renamed_path.write_text(json.dumps({"fields": renamed_fields}, indent=2))
        logger.info("Wrote renamed fields JSON to %s", renamed_path)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run sandbox field detection pipeline on a PDF."
    )
    parser.add_argument("pdf", type=Path, help="Path to input PDF file")
    parser.add_argument(
        "--output",
        type=Path,
        help="Directory or file path used to locate the output root (artifacts are temp-prefixed).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Root directory for json/ and overlays/ (overrides --output).",
    )
    parser.add_argument(
        "--pipeline",
        choices=["auto", "native", "scanned"],
        default="auto",
        help="Force pipeline selection (auto uses text-layer heuristic).",
    )
    parser.add_argument(
        "--openai",
        "--openAI",
        action="store_true",
        help="Run the OpenAI rename pass over full-page overlays.",
    )
    args = parser.parse_args()

    pdf_path: Path = args.pdf
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    output_root: Path | None
    if args.output_dir is not None:
        output_root = args.output_dir
    elif args.output is not None:
        if args.output.suffix.lower() == ".json":
            logger.info("Output path treated as root; artifacts will be temp-prefixed.")
            output_root = args.output.parent
        else:
            output_root = args.output
    else:
        output_root = None
    run_pipeline(
        pdf_path,
        output_root,
        pipeline=args.pipeline,
        openai=args.openai,
    )


if __name__ == "__main__":
    main()
