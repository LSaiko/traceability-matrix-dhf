"""Traceability matrix rendering (Markdown, PDF, stable JSON export)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from schemas import ConfidenceBand, LinkKind, TraceabilityMatrix, TraceLink

COLUMNS: tuple[tuple[str, LinkKind], ...] = (
    ("Design output", LinkKind.IMPLEMENTS),
    ("Verification", LinkKind.VERIFIES),
    ("Validation", LinkKind.VALIDATES),
    ("Risk control", LinkKind.MITIGATES),
)
# ponytail: band chips are plain text so the same string works in Markdown, PDF and grep.
CHIP = {
    ConfidenceBand.HIGH: "[HIGH]",
    ConfidenceBand.AMBIGUOUS: "[AMBIGUOUS]",
    ConfidenceBand.LOW: "[LOW]",
}
DISCLAIMER = (
    "This matrix is produced by the Archivist role. It links design inputs to design outputs, "
    "verification, validation and ISO 14971 risk controls and scores each link by three-band "
    "confidence: HIGH links pass through, AMBIGUOUS links are flagged for human interpretation "
    "with reasoning attached, LOW links are insufficient evidence and are not counted as "
    "coverage. It does not author requirements, fabricate evidence or close gaps; every gap "
    "requires a human disposition under 21 CFR 820.30(j) design history file review."
)


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


def _cell(links: list[TraceLink]) -> str:
    return "; ".join(f"{ln.source_id} {CHIP[ln.band]}" for ln in links) if links else "- [LOW]"


def render_markdown(m: TraceabilityMatrix) -> str:
    """Requirement x [design, verification, validation, risk] matrix plus gaps and notes."""
    by_target: defaultdict[str, defaultdict[LinkKind, list[TraceLink]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for ln in m.links:
        by_target[ln.target_id][ln.kind].append(ln)
    rows = [
        [r.id, r.level.value, r.status, *(_cell(by_target[r.id][k]) for _, k in COLUMNS)]
        for r in m.requirements
    ]
    parts = [
        f"# Traceability Matrix: {m.project_id}",
        f"Generated {m.generated_at.isoformat()} | overall band **{m.overall_band.value}** "
        f"| {len(m.links)} link(s) | {len(m.gaps)} gap(s)",
        "## Coverage (approved requirements, non-LOW links only)",
        _bullets([f"{k.replace('_', ' ')}: {v:.0%}" for k, v in m.coverage.items()]),
        "## Matrix",
        _table(["Requirement", "Level", "Status", *(c for c, _ in COLUMNS)], rows),
        "## Gaps",
        _table(
            ["Item", "Gap", "Severity", "Band", "Reasoning"],
            [[g.item_id, g.kind, g.severity, CHIP[g.band], g.reasoning] for g in m.gaps],
        )
        if m.gaps
        else "_No gaps detected. Human review of the matrix is still required._",
        "## Links",
        _table(
            ["Source", "Kind", "Target", "Confidence", "Band", "Reasoning"],
            [
                [
                    ln.source_id,
                    ln.kind.value,
                    ln.target_id,
                    f"{ln.confidence:.2f}",
                    CHIP[ln.band],
                    ln.reasoning,
                ]
                for ln in m.links
            ],
        ),
        "## IEC 62304 Software Lifecycle",
        m.iec_62304_note,
        "## ISO 14971 Risk Management",
        m.iso_14971_note,
        _bullets(
            [
                f"{rc.id} {rc.hazard} (S{rc.severity} x P{rc.probability} = {rc.risk_index}): "
                f"{rc.control_measure} -> {', '.join(rc.requirement_ids) or 'no requirement'}; "
                f"residual risk acceptable: {rc.residual_risk_acceptable}"
                for rc in m.risk_controls
            ]
        )
        or "_No risk controls recorded._",
        "## Validation Evidence Log",
        _bullets(
            [
                f"{v.id} `{v.evidence_id}` from {v.source} ({v.generated_at.isoformat()}): "
                f"{v.summary}"
                for v in m.validations
            ]
        )
        or "_No validation evidence ingested._",
        "## Archivist Disclaimer",
        DISCLAIMER,
    ]
    return "\n\n".join(parts) + "\n"


def render_pdf(m: TraceabilityMatrix, out: Path) -> Path:
    """Render the Markdown matrix into a simple reportlab PDF (headings, paragraphs, tables)."""
    styles = getSampleStyleSheet()
    story: list[object] = []
    grid = TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]
    )
    for block in render_markdown(m).split("\n\n"):
        if block.startswith("|"):
            rows = [[c.strip() for c in ln.strip("|").split("|")] for ln in block.splitlines()]
            cells = [[Paragraph(escape(c), styles["BodyText"]) for c in r] for r in rows]
            story.append(Table([cells[0], *cells[2:]], style=grid, hAlign="LEFT"))
        elif block.startswith("#"):
            level = len(block) - len(block.lstrip("#"))
            story.append(Paragraph(escape(block.lstrip("# ")), styles[f"Heading{min(level, 3)}"]))
        else:
            story.append(Paragraph(escape(block).replace("\n", "<br/>"), styles["BodyText"]))
        story.append(Spacer(1, 6))
    out.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(out), title=f"Traceability Matrix {m.project_id}").build(story)
    return out


def export_json(m: TraceabilityMatrix, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(m.model_dump_json(indent=2), encoding="utf-8")
    return out


__all__ = ["export_json", "render_markdown", "render_pdf"]


if __name__ == "__main__":  # python -m app.report -> refresh docs/traceability-matrix.schema.json
    import json

    target = Path(__file__).resolve().parents[1] / "docs" / "traceability-matrix.schema.json"
    target.write_text(
        json.dumps(TraceabilityMatrix.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    print(target)
