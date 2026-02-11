import re
from pathlib import Path

from backend.fieldDetecting.rename_pipeline.combinedSrc import output_layout


def test_ensure_output_layout_creates_expected_directories(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"

    layout = output_layout.ensure_output_layout(root)

    assert layout.root == root
    assert layout.json_dir == root / "json"
    assert layout.overlays_dir == root / "overlays"
    assert layout.json_dir.is_dir()
    assert layout.overlays_dir.is_dir()


def test_temp_prefix_from_pdf_uses_stem_and_hash(tmp_path: Path) -> None:
    pdf_a = tmp_path / "forms" / "Patient_Intake.pdf"
    pdf_b = tmp_path / "other" / "Patient_Intake.pdf"

    prefix_a = output_layout.temp_prefix_from_pdf(pdf_a)
    prefix_b = output_layout.temp_prefix_from_pdf(pdf_b)

    assert prefix_a.startswith("temppatientake_")
    assert re.fullmatch(r"temp[a-z0-9_.-]+_[0-9a-f]{6}", prefix_a)
    assert prefix_a != prefix_b


def test_temp_prefix_from_pdf_outside_cwd_and_fallback() -> None:
    outside_pdf = Path("/tmp/outside/sample.pdf")
    fallback_prefix = output_layout.temp_prefix_from_pdf(Path(""), fallback="fallback")
    outside_prefix = output_layout.temp_prefix_from_pdf(outside_pdf)

    assert outside_prefix.startswith("tempsamplample_")
    assert fallback_prefix.startswith("tempfallblback_")
