"""FastAPI surface for the Archivist: DHF items in, traceability matrix out."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import jsonschema
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.core import build_matrix
from app.report import render_markdown
from app.store import SqliteStore, TraceabilityStore, db_path
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.store = SqliteStore(db_path())
    yield


app = FastAPI(title="traceability-matrix-dhf", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_store(request: Request) -> TraceabilityStore:
    store: TraceabilityStore = request.app.state.store
    return store


Store = Annotated[TraceabilityStore, Depends(get_store)]

Item = Requirement | DesignOutput | VerificationRecord | RiskControl
# ponytail: the id pattern on each model is the discriminator; pydantic's union picks the type.
_LIST_FOR: dict[type, str] = {
    Requirement: "requirements",
    DesignOutput: "design_outputs",
    VerificationRecord: "verifications",
    RiskControl: "risk_controls",
}


def _project(store: TraceabilityStore, project_id: str) -> DhfProject:
    project = store.get(project_id)
    if project is None:
        raise HTTPException(404, f"no project {project_id!r}")
    return project


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
def post_project(project: DhfProject, store: Store) -> DhfProject:
    store.put(project)
    return project


@app.get("/project/{project_id}")
def get_project(project_id: str, store: Store) -> DhfProject:
    return _project(store, project_id)


@app.post("/project/{project_id}/items")
def post_item(project_id: str, item: Item, store: Store) -> Item:
    project = _project(store, project_id)
    _upsert(getattr(project, _LIST_FOR[type(item)]), item)
    store.put(project)
    return item


@app.post("/project/{project_id}/evidence")
def post_evidence(
    project_id: str, payload: dict[str, Any], store: Store
) -> ValidationEvidenceRecord:
    project = _project(store, project_id)
    try:
        record = ValidationEvidenceRecord.from_validation_evidence(
            payload, f"VAL-{len(project.validations) + 1}"
        )
    except jsonschema.ValidationError as e:
        raise HTTPException(400, f"ValidationEvidence rejected: {e.message}") from e
    project.validations.append(record)
    store.put(project)
    return record


@app.get("/project/{project_id}/matrix", response_model=None)
def get_matrix(
    project_id: str, store: Store, format: str = "json"
) -> TraceabilityMatrix | PlainTextResponse:
    matrix = build_matrix(_project(store, project_id))
    if format == "markdown":
        return PlainTextResponse(render_markdown(matrix), media_type="text/markdown")
    return matrix


@app.get("/project/{project_id}/gaps")
def get_gaps(project_id: str, store: Store) -> dict[str, ConfidenceBand | list[Gap]]:
    matrix = build_matrix(_project(store, project_id))
    return {"overall_band": matrix.overall_band, "gaps": matrix.gaps}
