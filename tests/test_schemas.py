import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
from pydantic import BaseModel, ValidationError

from schemas import (
    ConfidenceBand,
    DesignOutput,
    DhfProject,
    Gap,
    Iec62304Class,
    Requirement,
    RequirementLevel,
    RiskControl,
    TraceLink,
    ValidationEvidenceRecord,
    VerificationRecord,
    band_for,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVIDENCE = json.loads((FIXTURES / "validation_evidence.json").read_text(encoding="utf-8"))
TS = datetime(2026, 3, 1, tzinfo=UTC)

REQ = Requirement(
    id="REQ-1",
    level=RequirementLevel.SYSTEM,
    text="The device shall flag AUC drift beyond 0.02.",
    rationale="PCCP boundary",
    iec_62304_class=Iec62304Class.B,
    acceptance_criteria=["drift > 0.02 flagged"],
    status="approved",
)
SRS = Requirement(
    id="SRS-3",
    level=RequirementLevel.SOFTWARE,
    text="Drift detector shall use a two-proportion z-test.",
    parent_id="REQ-1",
    iec_62304_class=Iec62304Class.B,
    status="approved",
)
DO = DesignOutput(
    id="DO-1", title="drift module", artifact_path="app/core.py", requirement_ids=["REQ-1", "SRS-3"]
)
VER = VerificationRecord(
    id="VER-1",
    method="test",
    description="unit tests",
    requirement_ids=["REQ-1", "SRS-3"],
    result="pass",
    executed_at=TS,
    evidence_ref="tests/test_core.py",
)
VAL = ValidationEvidenceRecord.from_validation_evidence(EVIDENCE)
RC = RiskControl(
    id="RC-1",
    hazard="Undetected performance drift",
    hazardous_situation="Model degrades silently in production",
    harm="Missed diagnosis",
    severity=4,
    probability=3,
    control_measure="Automated drift detection with human review",
    requirement_ids=["REQ-1"],
    verification_ids=["VER-1"],
    residual_risk_acceptable=True,
)
PROJECT = DhfProject(
    project_id="dhf-1",
    name="Triage SaMD",
    device_description="ML triage classifier",
    intended_use="Prioritise studies for radiologist review",
    iec_62304_class=Iec62304Class.B,
    requirements=[REQ, SRS],
    design_outputs=[DO],
    verifications=[VER],
    validations=[VAL],
    risk_controls=[RC],
)
LINK = TraceLink(
    source_id="DO-1",
    target_id="REQ-1",
    kind="implements",
    confidence=0.9,
    band=band_for(0.9),
    reasoning="explicit id match",
)
GAP = Gap(
    item_id="REQ-2",
    kind="missing_verification",
    severity="high",
    band=ConfidenceBand.LOW,
    reasoning="no verification record",
)


@pytest.mark.parametrize("obj", [REQ, SRS, DO, VER, VAL, RC, PROJECT, LINK, GAP])
def test_round_trip(obj: BaseModel) -> None:
    assert type(obj).model_validate_json(obj.model_dump_json()) == obj


def test_from_validation_evidence_maps_fields() -> None:
    assert VAL.source == "ml-samd-validator"
    assert VAL.evidence_id == EVIDENCE["evidence_id"] and len(VAL.evidence_id) == 36
    assert VAL.requirement_ids == ["REQ-1", "SRS-3"] and VAL.model_id == "m1"
    assert VAL.overall_band is ConfidenceBand.LOW and VAL.requires_human_review is True
    assert VAL.generated_at.isoformat().startswith(EVIDENCE["generated_at"][:19])
    assert "m1 v1.0.0" in VAL.summary and "requires human review" in VAL.summary
    assert VAL.raw == EVIDENCE
    ok = ValidationEvidenceRecord.from_validation_evidence(
        {**EVIDENCE, "drift": {**EVIDENCE["drift"], "requires_human_review": False}}, "VAL-2"
    )
    assert ok.id == "VAL-2" and "no human review" in ok.summary


def test_from_validation_evidence_rejects_missing_evidence_id() -> None:
    payload = {k: v for k, v in EVIDENCE.items() if k != "evidence_id"}
    with pytest.raises(jsonschema.ValidationError):
        ValidationEvidenceRecord.from_validation_evidence(payload)


def test_risk_index_and_bands() -> None:
    assert RC.risk_index == 12 and RC.model_copy(update={"risk_index": 1}).risk_index == 1
    assert RiskControl.model_validate({**RC.model_dump(), "risk_index": 99}).risk_index == 12
    assert [band_for(c) for c in (0.8, 0.79, 0.55, 0.54)] == [
        ConfidenceBand.HIGH,
        ConfidenceBand.AMBIGUOUS,
        ConfidenceBand.AMBIGUOUS,
        ConfidenceBand.LOW,
    ]


def test_extra_forbidden_and_id_patterns() -> None:
    with pytest.raises(ValidationError):
        Requirement.model_validate({**REQ.model_dump(), "bogus": 1})
    with pytest.raises(ValidationError):
        Requirement.model_validate({**REQ.model_dump(), "id": "DO-1"})
    with pytest.raises(ValidationError):
        RiskControl.model_validate({**RC.model_dump(), "severity": 6})
