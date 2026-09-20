# traceability-matrix-dhf

[![CI](https://github.com/LSaiko/traceability-matrix-dhf/actions/workflows/ci.yml/badge.svg)](https://github.com/LSaiko/traceability-matrix-dhf/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**The Archivist: links design-input requirements to design outputs, verification and
validation evidence, and ISO 14971 risk controls inside a Design History File, and reports
where the chain is broken.**

Portfolio project for Software as a Medical Device design controls (FDA 21 CFR 820.30,
IEC 62304, ISO 14971). Ingests `ValidationEvidence` JSON exported by
[ml-samd-validator](https://github.com/LSaiko/ml-samd-validator) (`schemas/validation-evidence.schema.json`,
byte-identical to the sibling's copy) and scores every trace link with three-band
confidence: HIGH (>= 0.80) pass-through, AMBIGUOUS (0.55-0.79) flagged for human
interpretation, LOW (< 0.55) insufficient evidence. It never closes a gap on its own.

## Dev

```
pip install -e .[dev]
pytest
uvicorn app.main:app --reload
cd dashboard && npm install && npm run build
```
