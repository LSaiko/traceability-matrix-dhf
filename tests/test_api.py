import json
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel
from test_core import CLEAN
from test_schemas import EVIDENCE, RC, REQ, VER

from app.main import app, projects

client = TestClient(app)
PID = CLEAN.project_id


def setup_function() -> None:
    projects.clear()


def dump(obj: BaseModel) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(obj.model_dump_json())
    return out


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_404s_without_project() -> None:
    for path in ("", "/matrix", "/gaps"):
        assert client.get(f"/project/nope{path}").status_code == 404
    assert client.post("/project/nope/items", json=dump(REQ)).status_code == 404
    assert client.post("/project/nope/evidence", json=EVIDENCE).status_code == 404


def test_full_flow_evidence_changes_coverage() -> None:
    bare = CLEAN.model_copy(update={"validations": []})
    r = client.post("/project", json=dump(bare))
    assert r.status_code == 200 and r.json()["project_id"] == PID
    assert client.get(f"/project/{PID}").json() == dump(bare)

    before = client.get(f"/project/{PID}/matrix").json()
    assert before["coverage"]["validation"] == 0.0
    assert {g["kind"] for g in before["gaps"]} == {"missing_validation"}

    r = client.post(f"/project/{PID}/evidence", json=EVIDENCE)
    assert r.status_code == 200
    rec = r.json()
    assert rec["id"] == "VAL-1" and rec["source"] == "ml-samd-validator"
    assert rec["evidence_id"] == EVIDENCE["evidence_id"] and rec["overall_band"] == "LOW"

    after = client.get(f"/project/{PID}/matrix").json()
    links = [ln for ln in after["links"] if ln["kind"] == "validates"]
    assert {(ln["source_id"], ln["target_id"]) for ln in links} == {
        ("VAL-1", "REQ-1"),
        ("VAL-1", "SRS-3"),
    }
    assert all(ln["band"] == "LOW" for ln in links)  # fixture evidence is LOW + review
    assert after["coverage"]["validation"] == 0.0  # LOW links never count as coverage
    assert {g["kind"] for g in after["gaps"]} == {"unreviewed_validation"}

    # a HIGH, reviewed package flips validation coverage to 100%
    drift = {**EVIDENCE["drift"], "overall_band": "HIGH", "requires_human_review": False}
    good = {**EVIDENCE, "drift": drift}
    assert client.post(f"/project/{PID}/evidence", json=good).json()["id"] == "VAL-2"
    final = client.get(f"/project/{PID}/matrix").json()
    assert final["coverage"]["validation"] == 1.0
    assert {g["kind"] for g in final["gaps"]} == {"unreviewed_validation"}

    gaps = client.get(f"/project/{PID}/gaps").json()
    assert gaps["overall_band"] == "LOW" and gaps["gaps"] == final["gaps"]

    md = client.get(f"/project/{PID}/matrix", params={"format": "markdown"})
    assert md.headers["content-type"].startswith("text/markdown")
    assert md.text.startswith(f"# Traceability Matrix: {PID}") and "VAL-2 [HIGH]" in md.text


def test_items_upsert_by_id_prefix() -> None:
    client.post("/project", json=dump(CLEAN))
    failed = dump(VER.model_copy(update={"result": "fail"}))
    assert client.post(f"/project/{PID}/items", json=failed).json() == failed
    new_rc = dump(RC.model_copy(update={"id": "RC-2", "requirement_ids": []}))
    assert client.post(f"/project/{PID}/items", json=new_rc).status_code == 200
    draft = dump(REQ.model_copy(update={"status": "draft"}))
    client.post(f"/project/{PID}/items", json=draft)
    client.post(f"/project/{PID}/items", json={"id": "DO-9", "title": "t", "artifact_path": "p"})
    p = client.get(f"/project/{PID}").json()
    assert [v["result"] for v in p["verifications"]] == ["fail"]  # replaced, not appended
    assert [r["id"] for r in p["risk_controls"]] == ["RC-1", "RC-2"]
    assert p["requirements"][0]["status"] == "draft"
    assert [d["id"] for d in p["design_outputs"]] == ["DO-1", "DO-9"]
    kinds = {g["kind"] for g in client.get(f"/project/{PID}/gaps").json()["gaps"]}
    assert {"failed_verification", "unmitigated_risk", "orphan_design_output"} <= kinds
    assert client.post(f"/project/{PID}/items", json={"id": "XX-1"}).status_code == 422


def test_bad_evidence_is_400_with_schema_message() -> None:
    client.post("/project", json=dump(CLEAN))
    payload = {k: v for k, v in EVIDENCE.items() if k != "evidence_id"}
    r = client.post(f"/project/{PID}/evidence", json=payload)
    assert r.status_code == 400 and "evidence_id" in r.json()["detail"]
    assert client.get(f"/project/{PID}").json()["validations"] == [dump(CLEAN.validations[0])]
