"""Integration: SQLite persistence survives a store restart and the API runs end to end on it."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api import PID, dump
from test_core import CLEAN, UN
from test_schemas import EVIDENCE, PROJECT

from app.main import app, get_store
from app.store import SqliteStore, migrate

pytestmark = pytest.mark.integration


def test_every_record_type_round_trips_byte_identical(tmp_path: Path) -> None:
    db = tmp_path / "dhf.db"
    project = PROJECT.model_copy(update={"requirements": [*PROJECT.requirements, UN]})
    assert all(getattr(project, k) for k in type(project).model_fields if k.endswith("s"))
    SqliteStore(db).put(project)
    migrate(db)  # idempotent re-run must not touch data
    reloaded = SqliteStore(db).get(project.project_id)  # fresh object = process restart
    assert reloaded is not None
    assert reloaded.model_dump_json() == project.model_dump_json()
    assert SqliteStore(db).get("nope") is None


def test_put_replaces_items_and_keeps_order(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "dhf.db")
    store.put(PROJECT)
    fewer = PROJECT.model_copy(update={"requirements": PROJECT.requirements[::-1][:1]})
    store.put(fewer)
    got = SqliteStore(store.path).get(PID)
    assert got is not None and got.requirements == fewer.requirements


def test_api_end_to_end_survives_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DHF_DB_PATH", str(tmp_path / "sub" / "dhf.db"))
    app.dependency_overrides.pop(get_store, None)  # use the real startup wiring
    with TestClient(app) as client:
        assert client.post("/project", json=dump(CLEAN)).status_code == 200
        assert client.post(f"/project/{PID}/evidence", json=EVIDENCE).json()["id"] == "VAL-2"
        before = client.get(f"/project/{PID}/matrix").json()
    with TestClient(app) as client:  # new lifespan, new SqliteStore
        assert client.get(f"/project/{PID}").json()["validations"][1]["id"] == "VAL-2"
        after = client.get(f"/project/{PID}/matrix").json()
    assert {**after, "generated_at": None} == {**before, "generated_at": None}
