"""FastAPI surface for the Archivist: DHF items in, traceability matrix out."""

from __future__ import annotations

import os
from typing import Any

import jsonschema
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.core import build_matrix
from app.report import render_markdown
from schemas import (
    ConfidenceBand,
    DesignOutput,
    DhfProject,
    Gap,
    Requirement,
    RiskControl,
    TraceabilityMatrix,
    ValidationEvidenceRecord,
    VerificationRecord,
)

app = FastAPI(title="traceability-matrix-dhf")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ponytail: in-memory store, swap for sqlite if persistence needed
projects: dict[str, DhfProject] = {}

Item = Requirement | DesignOutput | VerificationRecord | RiskControl
# ponytail: the id pattern on each model is the discriminator; pydantic's union picks the type.
_LIST_FOR: dict[type, str] = {
    Requirement: "requirements",
    DesignOutput: "design_outputs",
    VerificationRecord: "verifications",
    RiskControl: "risk_controls",
}


def _project(project_id: str) -> DhfProject:
    if project_id not in projects:
        raise HTTPException(404, f"no project {project_id!r}")
    return projects[project_id]


def _upsert(items: list[Any], item: Any) -> None:
    ids = [i.id for i in items]
    if item.id in ids:
        items[ids.index(item.id)] = item
    else:
        items.append(item)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/project")
def post_project(project: DhfProject) -> DhfProject:
    projects[project.project_id] = project
    return project


@app.get("/project/{project_id}")
def get_project(project_id: str) -> DhfProject:
    return _project(project_id)


@app.post("/project/{project_id}/items")
def post_item(project_id: str, item: Item) -> Item:
    _upsert(getattr(_project(project_id), _LIST_FOR[type(item)]), item)
    return item


@app.post("/project/{project_id}/evidence")
def post_evidence(project_id: str, payload: dict[str, Any]) -> ValidationEvidenceRecord:
    project = _project(project_id)
    try:
        record = ValidationEvidenceRecord.from_validation_evidence(
            payload, f"VAL-{len(project.validations) + 1}"
        )
    except jsonschema.ValidationError as e:
        raise HTTPException(400, f"ValidationEvidence rejected: {e.message}") from e
    project.validations.append(record)
    return record


@app.get("/project/{project_id}/matrix", response_model=None)
def get_matrix(project_id: str, format: str = "json") -> TraceabilityMatrix | PlainTextResponse:
    matrix = build_matrix(_project(project_id))
    if format == "markdown":
        return PlainTextResponse(render_markdown(matrix), media_type="text/markdown")
    return matrix


@app.get("/project/{project_id}/gaps")
def get_gaps(project_id: str) -> dict[str, ConfidenceBand | list[Gap]]:
    matrix = build_matrix(_project(project_id))
    return {"overall_band": matrix.overall_band, "gaps": matrix.gaps}
