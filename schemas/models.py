"""Pydantic v2 schemas for traceability-matrix-dhf (21 CFR 820.30 / IEC 62304 / ISO 14971)."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

_HERE = Path(__file__).resolve().parent
VALIDATION_EVIDENCE_SCHEMA_FILE = _HERE / "validation-evidence.schema.json"
VALIDATION_EVIDENCE_SCHEMA: dict[str, Any] = json.loads(
    VALIDATION_EVIDENCE_SCHEMA_FILE.read_text(encoding="utf-8")
)
# The exporter defaults evidence_id/requirement_ids, so the contract file leaves them optional;
# ingestion additionally requires both because they are the binding keys into the DHF.
BINDING_KEYS = ("evidence_id", "requirement_ids")
_INGEST_SCHEMA: dict[str, Any] = {
    **VALIDATION_EVIDENCE_SCHEMA,
    "required": [*VALIDATION_EVIDENCE_SCHEMA["required"], *BINDING_KEYS],
}


class ItemKind(StrEnum):
    REQUIREMENT = "requirement"
    DESIGN_OUTPUT = "design_output"
    VERIFICATION = "verification"
    VALIDATION = "validation"
    RISK_CONTROL = "risk_control"


class RequirementLevel(StrEnum):
    """IEC 62304 §5.2 flavour: user need -> system requirement -> software requirement."""

    USER_NEED = "user_need"
    SYSTEM = "system"
    SOFTWARE = "software"


class LinkKind(StrEnum):
    IMPLEMENTS = "implements"
    VERIFIES = "verifies"
    VALIDATES = "validates"
    MITIGATES = "mitigates"


class ConfidenceBand(StrEnum):
    HIGH = "HIGH"
    AMBIGUOUS = "AMBIGUOUS"
    LOW = "LOW"


class Iec62304Class(StrEnum):
    A = "A"
    B = "B"
    C = "C"


def band_for(confidence: float) -> ConfidenceBand:
    """Three-band routing: >=0.80 HIGH, 0.55-0.79 AMBIGUOUS, <0.55 LOW."""
    if confidence >= 0.80:
        return ConfidenceBand.HIGH
    if confidence >= 0.55:
        return ConfidenceBand.AMBIGUOUS
    return ConfidenceBand.LOW


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requirement(_Strict):
    id: str = Field(pattern=r"^(REQ|UN|SRS)-\d+$")
    level: RequirementLevel
    text: str = Field(min_length=1)
    rationale: str = ""
    parent_id: str | None = None
    iec_62304_class: Iec62304Class
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: Literal["draft", "approved", "obsolete"] = "draft"


class DesignOutput(_Strict):
    id: str = Field(pattern=r"^DO-\d+$")
    title: str = Field(min_length=1)
    description: str = ""
    artifact_path: str = Field(min_length=1)
    requirement_ids: list[str] = Field(default_factory=list)


class VerificationRecord(_Strict):
    id: str = Field(pattern=r"^VER-\d+$")
    method: Literal["test", "inspection", "analysis", "demonstration"]
    description: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    result: Literal["pass", "fail", "blocked"]
    executed_at: datetime
    evidence_ref: str = Field(min_length=1)


class ValidationEvidenceRecord(_Strict):
    id: str = Field(pattern=r"^VAL-\d+$")
    source: Literal["ml-samd-validator", "manual"]
    evidence_id: str = Field(min_length=1)
    requirement_ids: list[str] = Field(default_factory=list)
    model_id: str = Field(min_length=1)
    overall_band: ConfidenceBand
    requires_human_review: bool
    generated_at: datetime
    summary: str
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_validation_evidence(
        cls, payload: dict[str, Any], record_id: str = "VAL-1"
    ) -> ValidationEvidenceRecord:
        """Ingest an ml-samd-validator ValidationEvidence export, validated against the contract."""
        jsonschema.validate(payload, _INGEST_SCHEMA, cls=jsonschema.Draft202012Validator)
        drift = payload["drift"]
        review = "requires" if drift["requires_human_review"] else "no"
        summary = (
            f"{payload['model_id']} v{payload['version']}: drift {drift['overall_band']} "
            f"over {len(drift['metrics'])} metric(s), {review} human review, "
            f"fairness flagged={payload['fairness']['any_flagged']}"
        )
        return cls(
            id=record_id,
            source="ml-samd-validator",
            evidence_id=payload["evidence_id"],
            requirement_ids=list(payload["requirement_ids"]),
            model_id=payload["model_id"],
            overall_band=ConfidenceBand(drift["overall_band"]),
            requires_human_review=drift["requires_human_review"],
            generated_at=payload["generated_at"],
            summary=summary,
            raw=payload,
        )


class RiskControl(_Strict):
    """ISO 14971 hazard -> hazardous situation -> harm, with the control traced to requirements."""

    id: str = Field(pattern=r"^RC-\d+$")
    hazard: str = Field(min_length=1)
    hazardous_situation: str = ""
    harm: str = ""
    severity: int = Field(ge=1, le=5)
    probability: int = Field(ge=1, le=5)
    control_measure: str = Field(min_length=1)
    requirement_ids: list[str] = Field(default_factory=list)
    verification_ids: list[str] = Field(default_factory=list)
    residual_risk_acceptable: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _drop_risk_index(cls, data: Any) -> Any:
        """Accept our own dumps back: risk_index is derived, never an input."""
        return (
            {k: v for k, v in data.items() if k != "risk_index"} if isinstance(data, dict) else data
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def risk_index(self) -> int:
        return self.severity * self.probability


class TraceLink(_Strict):
    source_id: str
    target_id: str
    kind: LinkKind
    confidence: float = Field(ge=0.0, le=1.0)
    band: ConfidenceBand
    reasoning: str


GapKind = Literal[
    "missing_design_output",
    "missing_verification",
    "missing_validation",
    "failed_verification",
    "unmitigated_risk",
    "orphan_design_output",
    "orphan_evidence",
    "unreviewed_validation",
]


class Gap(_Strict):
    item_id: str
    kind: GapKind
    severity: Literal["high", "medium", "low"]
    band: ConfidenceBand
    reasoning: str


class DhfProject(_Strict):
    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    device_description: str = ""
    intended_use: str = ""
    iec_62304_class: Iec62304Class
    requirements: list[Requirement] = Field(default_factory=list)
    design_outputs: list[DesignOutput] = Field(default_factory=list)
    verifications: list[VerificationRecord] = Field(default_factory=list)
    validations: list[ValidationEvidenceRecord] = Field(default_factory=list)
    risk_controls: list[RiskControl] = Field(default_factory=list)


class TraceabilityMatrix(_Strict):
    project_id: str
    generated_at: datetime
    requirements: list[Requirement]
    design_outputs: list[DesignOutput]
    verifications: list[VerificationRecord]
    validations: list[ValidationEvidenceRecord]
    risk_controls: list[RiskControl]
    links: list[TraceLink]
    gaps: list[Gap]
    coverage: dict[str, float]
    overall_band: ConfidenceBand
    iec_62304_note: str
    iso_14971_note: str
