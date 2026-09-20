# TraceabilityMatrix schema and the ValidationEvidence ingestion contract

Two JSON contracts live in this repository:

| File | Direction | Owner |
|---|---|---|
| `schemas/validation-evidence.schema.json` | **in** | [ml-samd-validator](https://github.com/LSaiko/ml-samd-validator) (`docs/validation-evidence.schema.json`); kept byte-identical here |
| `docs/traceability-matrix.schema.json` | **out** | this project; regenerated with `python -m app.report`, `tests/test_report.py` fails if it drifts from `TraceabilityMatrix.model_json_schema()` |

All models are Pydantic v2 with `extra="forbid"`: unknown keys are rejected.

## Ingestion contract: `ValidationEvidence` -> `ValidationEvidenceRecord`

`ValidationEvidenceRecord.from_validation_evidence(payload)` validates the payload with
`jsonschema` (Draft 2020-12) against `schemas/validation-evidence.schema.json` **plus** two
extra `required` keys, then maps it. The extra keys are the binding keys into the DHF; the
exporter defaults them, so its own schema leaves them optional, but an evidence package that
does not carry them cannot be traced and is rejected with `jsonschema.ValidationError`.

| ValidationEvidence field | ValidationEvidenceRecord field | Role |
|---|---|---|
| `evidence_id` (UUID4) | `evidence_id` | Identity of the evidence package. Every `validates` link cites it, so a reviewer can pull the exact package from the Inspector's log. |
| `requirement_ids` | `requirement_ids` | The DHF requirements this evidence validates. The DHF owner fills this list before or after export; each id becomes one `validates` link (source = record id, target = requirement id). An id not present in the project yields an `orphan_evidence` gap. |
| `model_id` | `model_id` | Which model the evidence concerns. |
| `drift.overall_band` | `overall_band` | Drives link confidence: HIGH 0.9, AMBIGUOUS 0.65, LOW 0.4. |
| `drift.requires_human_review` | `requires_human_review` | Subtracts 0.1 from link confidence and raises an `unreviewed_validation` gap (medium, AMBIGUOUS). |
| `generated_at` | `generated_at` | When the Inspector produced the package. |
| whole payload | `raw` | Stored verbatim so the matrix export is self-contained. |
| derived | `summary` | One line: model, version, drift band, metric count, review flag, fairness flag. |

`source` is `"ml-samd-validator"` for ingested packages; `"manual"` records (e.g. a usability
validation report) are entered directly with the same shape and a free-form `evidence_id`.

## `TraceabilityMatrix` (output)

| Field | Type | Meaning |
|---|---|---|
| `project_id` | string | Copied from `DhfProject`. |
| `generated_at` | ISO 8601 datetime (UTC) | When the matrix was built. |
| `requirements` | `Requirement[]` | Design inputs (21 CFR 820.30(c)). `id` matches `REQ-n`, `UN-n` or `SRS-n`; `level` is `user_need` / `system` / `software` (IEC 62304 §5.2 decomposition); `status` is `draft` / `approved` / `obsolete`; `iec_62304_class` A/B/C. |
| `design_outputs` | `DesignOutput[]` | 820.30(d). `DO-n`, `artifact_path` points at the document or code, `requirement_ids` are the inputs it implements. |
| `verifications` | `VerificationRecord[]` | 820.30(f). `VER-n`, `method` test/inspection/analysis/demonstration, `result` pass/fail/blocked, `evidence_ref`. |
| `validations` | `ValidationEvidenceRecord[]` | 820.30(g). See ingestion contract above. |
| `risk_controls` | `RiskControl[]` | ISO 14971 §7. `RC-n`, hazard / hazardous situation / harm, `severity` and `probability` 1-5, `risk_index` = product (derived, ignored on input), `control_measure`, `requirement_ids` that implement it, `verification_ids` that verify it, `residual_risk_acceptable` (manufacturer's statement, may be null). |
| `links` | `TraceLink[]` | `source_id -> target_id` with `kind` (`implements`, `verifies`, `validates`, `mitigates`), `confidence` 0-1, `band`, `reasoning`. |
| `gaps` | `Gap[]` | `item_id`, `kind` (see below), `severity` high/medium/low, `band`, `reasoning`. |
| `coverage` | object | Fraction of **approved** requirements with at least one non-LOW link per kind: `design_output`, `verification`, `validation`, `risk_control`. |
| `overall_band` | HIGH / AMBIGUOUS / LOW | Worst band across all links (LOW when there are none). |
| `iec_62304_note`, `iso_14971_note` | string | Standards framing for the report; see `docs/architecture.md`. |

### Gap kinds

| Kind | Raised on | Severity |
|---|---|---|
| `missing_design_output` | approved requirement with no `implements` link | high for software level, else medium |
| `missing_verification` | approved requirement with no `verifies` link | high |
| `missing_validation` | approved requirement with no `validates` link | medium for user_need/system, low for software |
| `failed_verification` | approved requirement with a `fail` verification | high |
| `unmitigated_risk` | risk control with no known requirement, or no passing verification | high if `risk_index` >= 12, else medium |
| `orphan_design_output` | design output with no requirement, or an unknown one | low |
| `orphan_evidence` | verification, validation or risk control citing an unknown requirement | medium |
| `unreviewed_validation` | validation evidence with `requires_human_review` | medium, band AMBIGUOUS |

Requirement-level gaps carry the band of the best link that does exist for that requirement
(so a failed verification on an otherwise well-implemented requirement is a HIGH-band gap:
the Archivist is confident the gap is real), or LOW when nothing exists.

## Versioning

The ingestion contract follows the exporter's `schema_version` (currently `"1.0"`). To
refresh it, copy the sibling's `docs/validation-evidence.schema.json` over
`schemas/validation-evidence.schema.json` unchanged; `from_validation_evidence` reads the
`required` list from the file at import time, so no code change is needed for additive
changes.
