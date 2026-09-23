"""DHF record store: the Archivist's copy of each project's design-control records.

Only the source records are stored (requirements, design outputs, verification records,
validation evidence, ISO 14971 risk controls). Trace links and gaps are derived by
``build_matrix`` on every read, so a stored matrix can never drift from the records behind it.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol, get_origin

from pydantic import BaseModel

from schemas import (
    DesignOutput,
    DhfProject,
    Requirement,
    RiskControl,
    ValidationEvidenceRecord,
    VerificationRecord,
)


class TraceabilityStore(Protocol):
    def get(self, project_id: str) -> DhfProject | None: ...
    def put(self, project: DhfProject) -> None: ...


class InMemoryStore:
    """Process-lifetime store; used by the fast unit suite."""

    def __init__(self) -> None:
        self.projects: dict[str, DhfProject] = {}

    def get(self, project_id: str) -> DhfProject | None:
        return self.projects.get(project_id)

    def put(self, project: DhfProject) -> None:
        self.projects[project.project_id] = project


# DhfProject list field -> (table, model). One table per record type.
ITEM_TABLES: dict[str, tuple[str, type[BaseModel]]] = {
    "requirements": ("requirement", Requirement),
    "design_outputs": ("design_output", DesignOutput),
    "verifications": ("verification_record", VerificationRecord),
    "validations": ("validation_evidence_record", ValidationEvidenceRecord),
    "risk_controls": ("risk_control", RiskControl),
}
PROJECT_FIELDS = [f for f in DhfProject.model_fields if f not in ITEM_TABLES]


def _json_fields(model: type[BaseModel]) -> set[str]:
    return {n for n, f in model.model_fields.items() if get_origin(f.annotation) in (list, dict)}


def _ddl() -> list[str]:
    # ponytail: columns mirror model_fields and carry no type affinity, so SQLite stores exactly
    # what pydantic dumped (TEXT affinity would turn bool 1 into '1'). Lists/dicts are JSON text.
    cols = ", ".join(PROJECT_FIELDS[1:])
    stmts = [f"CREATE TABLE IF NOT EXISTS project (project_id TEXT PRIMARY KEY, {cols})"]
    for table, model in ITEM_TABLES.values():
        fields = ", ".join(f for f in model.model_fields if f != "id")
        stmts.append(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            "project_id TEXT NOT NULL REFERENCES project(project_id) ON DELETE CASCADE, "
            f"position INTEGER NOT NULL, id TEXT NOT NULL, {fields}, "
            "PRIMARY KEY (project_id, id))"
        )
    return stmts


def migrate(path: Path) -> None:
    """Idempotent schema migration: safe to run on every startup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        for stmt in _ddl():
            conn.execute(stmt)


def db_path() -> Path:
    return Path(os.getenv("DHF_DB_PATH", "data/dhf.db"))


class SqliteStore:
    """Single-file SQLite store. A put replaces the whole project in one transaction."""

    def __init__(self, path: Path) -> None:
        self.path = path
        migrate(path)

    def _connect(self) -> sqlite3.Connection:
        # ponytail: a connection per call keeps FastAPI's threadpool safe without a pool.
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def get(self, project_id: str) -> DhfProject | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM project WHERE project_id = ?", (project_id,))
            head = row.fetchone()
            if head is None:
                return None
            data: dict[str, Any] = dict(head)
            for key, (table, model) in ITEM_TABLES.items():
                js = _json_fields(model)
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE project_id = ? ORDER BY position", (project_id,)
                )
                data[key] = [
                    {
                        k: json.loads(v) if k in js else v
                        for k, v in dict(r).items()
                        if k not in ("project_id", "position")
                    }
                    for r in rows
                ]
        return DhfProject.model_validate(data)

    def put(self, project: DhfProject) -> None:
        # ponytail: delete-and-reinsert the whole project; O(records) per write, fine at DHF
        # scale. Switch to per-item upserts if projects grow to thousands of records.
        dumped = project.model_dump(mode="json")
        pid = project.project_id
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM project WHERE project_id = ?", (pid,))  # cascades items
            conn.execute(
                f"INSERT INTO project ({', '.join(PROJECT_FIELDS)}) "
                f"VALUES ({', '.join('?' * len(PROJECT_FIELDS))})",
                [dumped[f] for f in PROJECT_FIELDS],
            )
            for key, (table, model) in ITEM_TABLES.items():
                fields = list(model.model_fields)  # excludes computed risk_index
                js = _json_fields(model)
                conn.executemany(
                    f"INSERT INTO {table} (project_id, position, {', '.join(fields)}) "
                    f"VALUES (?, ?, {', '.join('?' * len(fields))})",
                    [
                        [pid, pos, *(json.dumps(item[f]) if f in js else item[f] for f in fields)]
                        for pos, item in enumerate(dumped[key])
                    ],
                )


if __name__ == "__main__":
    migrate(db_path())
    print(f"migrated {db_path()}")
