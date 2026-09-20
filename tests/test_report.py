import json
from pathlib import Path

from test_core import CLEAN
from test_schemas import PROJECT, VAL

from app.core import build_matrix
from app.report import DISCLAIMER, export_json, render_markdown, render_pdf
from schemas import DhfProject, Iec62304Class, TraceabilityMatrix

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "docs" / "traceability-matrix.schema.json"
MATRIX = build_matrix(PROJECT)  # fixture VAL is LOW + requires review -> gaps present


def test_markdown_matrix_gaps_and_standards() -> None:
    md = render_markdown(MATRIX)
    for needle in (
        "# Traceability Matrix: dhf-1",
        "| REQ-1 | system | approved | DO-1 [HIGH] | VER-1 [HIGH] | VAL-1 [LOW] | RC-1 [HIGH] |",
        "| SRS-3 | software | approved | DO-1 [HIGH] | VER-1 [HIGH] | VAL-1 [LOW] | - [LOW] |",
        "| VAL-1 | unreviewed_validation | medium | [AMBIGUOUS] |",
        "design output: 100%",
        "validation: 0%",
        "## IEC 62304 Software Lifecycle",
        "## ISO 14971 Risk Management",
        "RC-1 Undetected performance drift (S4 x P3 = 12)",
        f"`{VAL.evidence_id}` from ml-samd-validator",
        "## Archivist Disclaimer",
        DISCLAIMER,
    ):
        assert needle in md
    assert "overall band **LOW**" in md


def test_markdown_empty_sections() -> None:
    md = render_markdown(
        build_matrix(DhfProject(project_id="p", name="n", iec_62304_class=Iec62304Class.A))
    )
    assert "_No gaps detected." in md and "_No risk controls recorded._" in md
    assert "_No validation evidence ingested._" in md
    assert "_No gaps detected." in render_markdown(build_matrix(CLEAN))


def test_pdf_written(tmp_path: Path) -> None:
    out = render_pdf(MATRIX, tmp_path / "matrix.pdf")
    assert out.exists() and out.stat().st_size > 1024


def test_json_round_trip(tmp_path: Path) -> None:
    out = export_json(MATRIX, tmp_path / "matrix.json")
    assert TraceabilityMatrix.model_validate_json(out.read_text(encoding="utf-8")) == MATRIX


def test_json_schema_file_matches_model() -> None:
    """Regenerate with: python -m app.report (writes docs/traceability-matrix.schema.json)."""
    assert (
        json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
        == TraceabilityMatrix.model_json_schema()
    )
