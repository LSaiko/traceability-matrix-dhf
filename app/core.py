"""Archivist core: build a scored requirements traceability matrix and its gap list.

Every link is scored 0-1 and routed by ``band_for``: HIGH links pass through, AMBIGUOUS links
are flagged for human interpretation with the reasoning attached, LOW links are reported as
insufficient evidence and never counted as coverage. Nothing here closes a gap on its own.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from schemas import (
    ConfidenceBand,
    DhfProject,
    Gap,
    GapKind,
    Iec62304Class,
    LinkKind,
    Requirement,
    RequirementLevel,
    RiskControl,
    TraceabilityMatrix,
    TraceLink,
    band_for,
)

# ponytail: explicit id match is the only evidence of a link we have; 0.9 leaves headroom for
# the status/result penalties below rather than pretending an id match is proof.
BASE_CONFIDENCE = 0.9
# ponytail: a draft target is not yet a design input (21 CFR 820.30(c)), so a link to it drops to
# AMBIGUOUS; an obsolete target drops to LOW.
STATUS_PENALTY = {"approved": 0.0, "draft": 0.15, "obsolete": 0.3}
# ponytail: failed verification is negative evidence; blocked is no evidence either way.
RESULT_CONFIDENCE = {"fail": 0.2, "blocked": 0.5}
# ponytail: reuse the exporter's own drift band as the validation link confidence.
BAND_CONFIDENCE = {
    ConfidenceBand.HIGH: 0.9,
    ConfidenceBand.AMBIGUOUS: 0.65,
    ConfidenceBand.LOW: 0.4,
}
REVIEW_PENALTY = 0.1
# ponytail: a link to an id that is not in the DHF cannot be assessed at all.
ORPHAN_CONFIDENCE = 0.1
UNMITIGATED_HIGH_RISK_INDEX = 12
COVERAGE_KEYS: dict[str, LinkKind] = {
    "design_output": LinkKind.IMPLEMENTS,
    "verification": LinkKind.VERIFIES,
    "validation": LinkKind.VALIDATES,
    "risk_control": LinkKind.MITIGATES,
}
BAND_ORDER = (ConfidenceBand.HIGH, ConfidenceBand.AMBIGUOUS, ConfidenceBand.LOW)

IEC_62304_NOTE = (
    "IEC 62304 software safety class {cls}: §5.1.1 requires the software development plan to "
    "establish traceability between system requirements, software requirements, software system "
    "tests and risk control measures; §5.2 (software requirements analysis) and §5.7 (software "
    "system testing) must demonstrate it. {req}"
)
IEC_62304_REQUIRED = "Traceability is mandatory for class B/C; gaps below block release."
IEC_62304_CLASS_A = "Class A relaxes documentation depth, but every gap still needs a disposition."
ISO_14971_NOTE = (
    "ISO 14971 §7: each hazard needs a risk control measure (§7.1) implemented as a requirement "
    "(§7.2) whose effectiveness is verified (§7.3). {n} risk control(s) recorded, {u} unmitigated. "
    "The residual-risk acceptability statement (§7.4, §8) is the manufacturer's; the Archivist "
    "reports the chain and does not assert acceptability."
)


def _status_link(
    source_id: str, req: Requirement, kind: LinkKind, base: float, why: str
) -> TraceLink:
    penalty = STATUS_PENALTY[req.status]
    conf = max(0.0, base - penalty)
    if penalty:
        why += f"; target {req.id} is {req.status} (-{penalty:.2f})"
    return TraceLink(
        source_id=source_id,
        target_id=req.id,
        kind=kind,
        confidence=conf,
        band=band_for(conf),
        reasoning=why,
    )


def _orphan_link(source_id: str, target_id: str, kind: LinkKind) -> TraceLink:
    return TraceLink(
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        confidence=ORPHAN_CONFIDENCE,
        band=ConfidenceBand.LOW,
        reasoning=f"target {target_id} does not exist in the DHF",
    )


def _gap(
    item_id: str, kind: GapKind, severity: str, why: str, band: ConfidenceBand = ConfidenceBand.LOW
) -> Gap:
    return Gap.model_validate(
        {"item_id": item_id, "kind": kind, "severity": severity, "band": band, "reasoning": why}
    )


def _risk_gap(rc: RiskControl, why: str) -> Gap:
    severity = "high" if rc.risk_index >= UNMITIGATED_HIGH_RISK_INDEX else "medium"
    return _gap(rc.id, "unmitigated_risk", severity, f"{rc.hazard}: {why}")


def build_matrix(project: DhfProject) -> TraceabilityMatrix:
    reqs = {r.id: r for r in project.requirements}
    vers = {v.id: v for v in project.verifications}
    links: list[TraceLink] = []
    gaps: list[Gap] = []
    # best confidence per requirement per link kind, and per requirement overall
    best: defaultdict[str, dict[LinkKind, float]] = defaultdict(dict)

    def add(link: TraceLink) -> None:
        links.append(link)
        kinds = best[link.target_id]
        kinds[link.kind] = max(kinds.get(link.kind, 0.0), link.confidence)

    for do in project.design_outputs:
        if not do.requirement_ids:
            gaps.append(
                _gap(
                    do.id,
                    "orphan_design_output",
                    "low",
                    f"{do.title} ({do.artifact_path}) traces to no requirement",
                )
            )
        for rid in do.requirement_ids:
            if rid in reqs:
                add(
                    _status_link(
                        do.id,
                        reqs[rid],
                        LinkKind.IMPLEMENTS,
                        BASE_CONFIDENCE,
                        f"{do.id} lists {rid} in requirement_ids",
                    )
                )
            else:
                add(_orphan_link(do.id, rid, LinkKind.IMPLEMENTS))
                gaps.append(
                    _gap(
                        do.id,
                        "orphan_design_output",
                        "low",
                        f"{do.id} traces to unknown requirement {rid}",
                    )
                )

    for ver in project.verifications:
        for rid in ver.requirement_ids:
            if rid not in reqs:
                add(_orphan_link(ver.id, rid, LinkKind.VERIFIES))
                gaps.append(
                    _gap(
                        ver.id,
                        "orphan_evidence",
                        "medium",
                        f"{ver.id} verifies unknown requirement {rid}",
                    )
                )
            elif ver.result == "pass":
                add(
                    _status_link(
                        ver.id,
                        reqs[rid],
                        LinkKind.VERIFIES,
                        BASE_CONFIDENCE,
                        f"{ver.method} {ver.id} passed ({ver.evidence_ref})",
                    )
                )
            else:
                conf = RESULT_CONFIDENCE[ver.result]
                why = (
                    "failed verification does not evidence coverage"
                    if ver.result == "fail"
                    else f"{ver.id} is blocked; no evidence either way"
                )
                add(
                    TraceLink(
                        source_id=ver.id,
                        target_id=rid,
                        kind=LinkKind.VERIFIES,
                        confidence=conf,
                        band=band_for(conf),
                        reasoning=why,
                    )
                )

    for val in project.validations:
        base = BAND_CONFIDENCE[val.overall_band]
        why = f"{val.source} evidence {val.evidence_id} band {val.overall_band.value}"
        if val.requires_human_review:
            base -= REVIEW_PENALTY
            why += f" (-{REVIEW_PENALTY:.2f}: requires human review)"
            gaps.append(
                _gap(
                    val.id,
                    "unreviewed_validation",
                    "medium",
                    f"{val.summary}; a qualified reviewer must disposition it",
                    ConfidenceBand.AMBIGUOUS,
                )
            )
        for rid in val.requirement_ids:
            if rid in reqs:
                add(_status_link(val.id, reqs[rid], LinkKind.VALIDATES, base, why))
            else:
                add(_orphan_link(val.id, rid, LinkKind.VALIDATES))
                gaps.append(
                    _gap(
                        val.id,
                        "orphan_evidence",
                        "medium",
                        f"{val.id} validates unknown requirement {rid}",
                    )
                )

    for rc in project.risk_controls:
        known = [rid for rid in rc.requirement_ids if rid in reqs]
        for rid in rc.requirement_ids:
            if rid in reqs:
                add(
                    _status_link(
                        rc.id,
                        reqs[rid],
                        LinkKind.MITIGATES,
                        BASE_CONFIDENCE,
                        f"{rc.control_measure} implemented by {rid}",
                    )
                )
            else:
                add(_orphan_link(rc.id, rid, LinkKind.MITIGATES))
                gaps.append(
                    _gap(
                        rc.id,
                        "orphan_evidence",
                        "medium",
                        f"{rc.id} mitigates via unknown requirement {rid}",
                    )
                )
        verified = [
            vid for vid in rc.verification_ids if vers.get(vid) and vers[vid].result == "pass"
        ]
        if not known:
            gaps.append(_risk_gap(rc, "control measure is not traced to any requirement"))
        elif not verified:
            gaps.append(_risk_gap(rc, "control measure has no passing verification"))

    approved = [r for r in project.requirements if r.status == "approved"]
    failed = defaultdict(list)
    for ver in project.verifications:
        if ver.result == "fail":
            for rid in ver.requirement_ids:
                failed[rid].append(ver.id)
    for req in approved:
        kinds = best[req.id]
        band = band_for(max(kinds.values())) if kinds else ConfidenceBand.LOW
        software = req.level is RequirementLevel.SOFTWARE
        if LinkKind.IMPLEMENTS not in kinds:
            gaps.append(
                _gap(
                    req.id,
                    "missing_design_output",
                    "high" if software else "medium",
                    f"no design output implements {req.id} (21 CFR 820.30(d))",
                    band,
                )
            )
        if LinkKind.VERIFIES not in kinds:
            gaps.append(
                _gap(
                    req.id,
                    "missing_verification",
                    "high",
                    f"no verification record covers {req.id} (21 CFR 820.30(f))",
                    band,
                )
            )
        if req.id in failed:
            gaps.append(
                _gap(
                    req.id,
                    "failed_verification",
                    "high",
                    f"{', '.join(failed[req.id])} failed against {req.id}",
                    band,
                )
            )
        if LinkKind.VALIDATES not in kinds:
            gaps.append(
                _gap(
                    req.id,
                    "missing_validation",
                    "low" if software else "medium",
                    f"no validation evidence covers {req.id} (21 CFR 820.30(g))",
                    band,
                )
            )

    # ponytail: coverage counts only non-LOW links; LOW means "do not assert coverage".
    coverage = {
        key: sum(1 for r in approved if best[r.id].get(kind, 0.0) >= 0.55) / len(approved)
        if approved
        else 0.0
        for key, kind in COVERAGE_KEYS.items()
    }
    overall = max((ln.band for ln in links), key=BAND_ORDER.index, default=ConfidenceBand.LOW)
    cls = project.iec_62304_class
    unmitigated = sum(1 for g in gaps if g.kind == "unmitigated_risk")
    return TraceabilityMatrix(
        project_id=project.project_id,
        generated_at=datetime.now(UTC),
        requirements=project.requirements,
        design_outputs=project.design_outputs,
        verifications=project.verifications,
        validations=project.validations,
        risk_controls=project.risk_controls,
        links=links,
        gaps=gaps,
        coverage=coverage,
        overall_band=overall,
        iec_62304_note=IEC_62304_NOTE.format(
            cls=cls.value,
            req=IEC_62304_CLASS_A if cls is Iec62304Class.A else IEC_62304_REQUIRED,
        ),
        iso_14971_note=ISO_14971_NOTE.format(n=len(project.risk_controls), u=unmitigated),
    )


__all__ = ["build_matrix"]
