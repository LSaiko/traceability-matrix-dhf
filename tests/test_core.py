from datetime import UTC, datetime

import pytest
from test_schemas import DO, PROJECT, RC, REQ, SRS, VAL, VER

from app.core import build_matrix
from schemas import (
    ConfidenceBand,
    DesignOutput,
    DhfProject,
    Gap,
    Iec62304Class,
    LinkKind,
    Requirement,
    RequirementLevel,
    RiskControl,
    TraceLink,
    ValidationEvidenceRecord,
    VerificationRecord,
)

VAL_HIGH = VAL.model_copy(
    update={"overall_band": ConfidenceBand.HIGH, "requires_human_review": False, "raw": {}}
)
CLEAN = PROJECT.model_copy(update={"validations": [VAL_HIGH]})
UN = Requirement(
    id="UN-1",
    level=RequirementLevel.USER_NEED,
    text="Radiologists need drifted models flagged.",
    iec_62304_class=Iec62304Class.B,
    status="approved",
)


def kinds(gaps: list[Gap]) -> list[tuple[str, str, str]]:
    return [(g.item_id, g.kind, g.severity) for g in gaps]


def link(links: list[TraceLink], source: str, target: str) -> TraceLink:
    (ln,) = [ln for ln in links if ln.source_id == source and ln.target_id == target]
    return ln


def test_fully_traced_project_is_high_with_no_gaps() -> None:
    m = build_matrix(CLEAN)
    assert m.gaps == [] and m.overall_band is ConfidenceBand.HIGH
    assert all(ln.band is ConfidenceBand.HIGH and ln.confidence == 0.9 for ln in m.links)
    assert {ln.kind for ln in m.links} == set(LinkKind)
    assert m.coverage == {
        "design_output": 1.0,
        "verification": 1.0,
        "validation": 1.0,
        "risk_control": 0.5,  # RC-1 mitigates REQ-1 only
    }
    assert m.project_id == "dhf-1" and m.generated_at.tzinfo is UTC
    assert "class B" in m.iec_62304_note and "mandatory" in m.iec_62304_note
    assert "1 risk control(s) recorded, 0 unmitigated" in m.iso_14971_note
    assert "manufacturer's" in m.iso_14971_note


def test_class_a_note_and_empty_project_coverage() -> None:
    m = build_matrix(DhfProject(project_id="p", name="n", iec_62304_class=Iec62304Class.A))
    assert "Class A relaxes" in m.iec_62304_note
    assert m.links == m.gaps == [] and m.overall_band is ConfidenceBand.LOW
    assert set(m.coverage.values()) == {0.0}


@pytest.mark.parametrize(
    ("status", "conf", "band"),
    [("draft", 0.75, ConfidenceBand.AMBIGUOUS), ("obsolete", 0.6, ConfidenceBand.AMBIGUOUS)],
)
def test_requirement_status_penalises_links(status: str, conf: float, band: ConfidenceBand) -> None:
    m = build_matrix(
        CLEAN.model_copy(update={"requirements": [REQ.model_copy(update={"status": status}), SRS]})
    )
    ln = link(m.links, "DO-1", "REQ-1")
    assert ln.confidence == pytest.approx(conf) and ln.band is band
    assert f"REQ-1 is {status}" in ln.reasoning
    assert m.overall_band is ConfidenceBand.AMBIGUOUS
    # non-approved requirements get no requirement-level gaps and drop out of coverage
    assert not [g for g in m.gaps if g.item_id == "REQ-1"]
    assert m.coverage["design_output"] == 1.0 and m.coverage["risk_control"] == 0.0


def test_failed_and_blocked_verification() -> None:
    failed = VER.model_copy(update={"result": "fail", "requirement_ids": ["REQ-1"]})
    blocked = VER.model_copy(
        update={"id": "VER-2", "result": "blocked", "requirement_ids": ["SRS-3"]}
    )
    m = build_matrix(CLEAN.model_copy(update={"verifications": [failed, blocked]}))
    f, b = link(m.links, "VER-1", "REQ-1"), link(m.links, "VER-2", "SRS-3")
    assert (f.confidence, f.band) == (0.2, ConfidenceBand.LOW)
    assert f.reasoning == "failed verification does not evidence coverage"
    assert (b.confidence, b.band) == (0.5, ConfidenceBand.LOW) and "blocked" in b.reasoning
    assert m.overall_band is ConfidenceBand.LOW and m.coverage["verification"] == 0.0
    # gap band reflects the best surviving link (DO-1 implements at 0.9 -> HIGH)
    (gap,) = [g for g in m.gaps if g.kind == "failed_verification"]
    assert (gap.item_id, gap.severity, gap.band) == ("REQ-1", "high", ConfidenceBand.HIGH)
    assert ("RC-1", "unmitigated_risk", "high") in kinds(m.gaps)  # VER-1 no longer passes


def test_missing_links_per_requirement_level() -> None:
    soft = SRS.model_copy(update={"id": "SRS-9"})
    bare = DhfProject(
        project_id="p",
        name="n",
        iec_62304_class=Iec62304Class.C,
        requirements=[UN, REQ, soft],
    )
    m = build_matrix(bare)
    assert m.overall_band is ConfidenceBand.LOW and all(
        g.band is ConfidenceBand.LOW for g in m.gaps
    )
    assert kinds(m.gaps) == [
        ("UN-1", "missing_design_output", "medium"),
        ("UN-1", "missing_verification", "high"),
        ("UN-1", "missing_validation", "medium"),
        ("REQ-1", "missing_design_output", "medium"),
        ("REQ-1", "missing_verification", "high"),
        ("REQ-1", "missing_validation", "medium"),
        ("SRS-9", "missing_design_output", "high"),
        ("SRS-9", "missing_verification", "high"),
        ("SRS-9", "missing_validation", "low"),
    ]
    assert "class C" in m.iec_62304_note


@pytest.mark.parametrize(
    ("rc", "severity", "phrase"),
    [
        (RC.model_copy(update={"requirement_ids": []}), "high", "not traced to any requirement"),
        (
            RC.model_copy(update={"verification_ids": ["VER-404"], "severity": 2}),
            "medium",
            "no passing verification",
        ),
    ],
)
def test_unmitigated_risk(rc: RiskControl, severity: str, phrase: str) -> None:
    m = build_matrix(CLEAN.model_copy(update={"risk_controls": [rc]}))
    (gap,) = [g for g in m.gaps if g.kind == "unmitigated_risk"]
    assert gap.severity == severity and phrase in gap.reasoning
    assert "1 unmitigated" in m.iso_14971_note


def test_orphan_design_output() -> None:
    none = DesignOutput(id="DO-2", title="stray", artifact_path="x.py")
    unknown = DO.model_copy(update={"id": "DO-3", "requirement_ids": ["REQ-404"]})
    m = build_matrix(CLEAN.model_copy(update={"design_outputs": [DO, none, unknown]}))
    assert ("DO-2", "orphan_design_output", "low") in kinds(m.gaps)
    assert ("DO-3", "orphan_design_output", "low") in kinds(m.gaps)
    orphan = link(m.links, "DO-3", "REQ-404")
    assert orphan.confidence == 0.1 and orphan.band is ConfidenceBand.LOW
    assert m.overall_band is ConfidenceBand.LOW


@pytest.mark.parametrize(
    ("band", "review", "conf", "expect"),
    [
        (ConfidenceBand.HIGH, False, 0.9, ConfidenceBand.HIGH),
        (ConfidenceBand.HIGH, True, 0.8, ConfidenceBand.HIGH),
        (ConfidenceBand.AMBIGUOUS, False, 0.65, ConfidenceBand.AMBIGUOUS),
        (ConfidenceBand.AMBIGUOUS, True, 0.55, ConfidenceBand.AMBIGUOUS),
        (ConfidenceBand.LOW, False, 0.4, ConfidenceBand.LOW),
        (ConfidenceBand.LOW, True, 0.3, ConfidenceBand.LOW),
    ],
)
def test_validation_link_follows_evidence_band(
    band: ConfidenceBand, review: bool, conf: float, expect: ConfidenceBand
) -> None:
    val = VAL_HIGH.model_copy(update={"overall_band": band, "requires_human_review": review})
    m = build_matrix(CLEAN.model_copy(update={"validations": [val]}))
    ln = link(m.links, "VAL-1", "REQ-1")
    assert ln.confidence == pytest.approx(conf) and ln.band is expect
    assert (f"band {band.value}" in ln.reasoning) and (("human review" in ln.reasoning) == review)
    unreviewed = [g for g in m.gaps if g.kind == "unreviewed_validation"]
    assert bool(unreviewed) is review
    if review:
        assert unreviewed[0].band is ConfidenceBand.AMBIGUOUS and unreviewed[0].severity == "medium"
    assert m.coverage["validation"] == (0.0 if expect is ConfidenceBand.LOW else 1.0)


def test_orphan_evidence_with_unknown_requirement_ids() -> None:
    ver = VerificationRecord(
        id="VER-7",
        method="analysis",
        requirement_ids=["REQ-404"],
        result="pass",
        executed_at=datetime(2026, 4, 1, tzinfo=UTC),
        evidence_ref="doc",
    )
    val = ValidationEvidenceRecord.from_validation_evidence(
        {**VAL.raw, "requirement_ids": ["SRS-404"]}, "VAL-9"
    )
    rc = RC.model_copy(update={"id": "RC-2", "requirement_ids": ["UN-404"]})
    m = build_matrix(
        CLEAN.model_copy(
            update={"verifications": [VER, ver], "validations": [val], "risk_controls": [RC, rc]}
        )
    )
    assert [(g.item_id, g.kind) for g in m.gaps if g.kind == "orphan_evidence"] == [
        ("VER-7", "orphan_evidence"),
        ("VAL-9", "orphan_evidence"),
        ("RC-2", "orphan_evidence"),
    ]
    assert ("RC-2", "unmitigated_risk", "high") in kinds(m.gaps)
    for src, tgt in (("VER-7", "REQ-404"), ("VAL-9", "SRS-404"), ("RC-2", "UN-404")):
        ln = link(m.links, src, tgt)
        assert ln.confidence == 0.1 and "does not exist" in ln.reasoning
