import type { Band, Gap, Link, LinkKind, Matrix, Severity, Validation } from "./types";

export const BAND_COLOR: Record<Band, string> = { HIGH: "#22d3ee", AMBIGUOUS: "#f97316", LOW: "#94a3b8" };
const COLUMNS: [string, LinkKind][] = [
  ["Design output", "implements"],
  ["Verification", "verifies"],
  ["Validation", "validates"],
  ["Risk control", "mitigates"],
];
const SEVERITY_RANK: Record<Severity, number> = { high: 0, medium: 1, low: 2 };
// coverage >= 0.80 HIGH, >= 0.55 AMBIGUOUS, else LOW: the same thresholds as link routing.
const coverageBand = (v: number): Band => (v >= 0.8 ? "HIGH" : v >= 0.55 ? "AMBIGUOUS" : "LOW");
const label = (s: string) => s.replace(/_/g, " ");

export const Chip = ({ band, label }: { band: Band; label?: string }) => (
  <span className="chip" style={{ background: BAND_COLOR[band] }}>{label ?? band}</span>
);

export const CoverageTiles = ({ coverage }: { coverage: Record<string, number> }) => (
  <div className="tiles">
    {Object.entries(coverage).map(([k, v]) => (
      <div key={k} className="tile" style={{ borderColor: BAND_COLOR[coverageBand(v)] }}>
        <div className="tile-value" style={{ color: BAND_COLOR[coverageBand(v)] }}>{Math.round(v * 100)}%</div>
        <div className="muted">{label(k)}</div>
      </div>
    ))}
  </div>
);

export function MatrixTable({ matrix }: { matrix: Matrix }) {
  const cell = (rid: string, kind: LinkKind) => {
    const links = matrix.links.filter((l) => l.target_id === rid && l.kind === kind);
    if (!links.length) return <span className="muted">-</span>;
    return links.map((l: Link) => (
      <span key={l.source_id} className="link" title={`${l.confidence.toFixed(2)}: ${l.reasoning}`}>
        {l.source_id} <Chip band={l.band} />
      </span>
    ));
  };
  return (
    <table>
      <thead>
        <tr><th>Requirement</th><th>Level</th><th>Status</th>{COLUMNS.map(([c]) => <th key={c}>{c}</th>)}</tr>
      </thead>
      <tbody>
        {matrix.requirements.map((r) => (
          <tr key={r.id} className={r.status === "approved" ? "" : "flagged"}>
            <td><code>{r.id}</code><div className="muted small">{r.text}</div></td>
            <td>{label(r.level)}</td>
            <td>{r.status}</td>
            {COLUMNS.map(([c, kind]) => <td key={c}>{cell(r.id, kind)}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export const GapTable = ({ gaps }: { gaps: Gap[] }) => (
  <table>
    <thead><tr><th>Gap</th><th>Item</th><th>Severity</th><th>Band</th><th>Reasoning</th></tr></thead>
    <tbody>
      {[...gaps]
        .sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
        .map((g, i) => (
          <tr key={i} className={g.severity === "high" ? "flagged" : ""}>
            <td>{label(g.kind)}</td>
            <td><code>{g.item_id}</code></td>
            <td>{g.severity}</td>
            <td><Chip band={g.band} /></td>
            <td className="muted">{g.reasoning}</td>
          </tr>
        ))}
    </tbody>
  </table>
);

export const EvidenceLog = ({ validations }: { validations: Validation[] }) => (
  <table>
    <thead><tr><th>Id</th><th>Source</th><th>Model</th><th>Evidence id</th><th>Band</th><th>Review</th><th>Summary</th></tr></thead>
    <tbody>
      {validations.map((v) => (
        <tr key={v.id} className={v.requires_human_review ? "flagged" : ""}>
          <td><code>{v.id}</code></td>
          <td>{v.source}</td>
          <td>{v.model_id}</td>
          <td className="muted small">{v.evidence_id}</td>
          <td><Chip band={v.overall_band} /></td>
          <td>{v.requires_human_review ? <span className="review">required</span> : "no"}</td>
          <td className="muted">{v.summary}</td>
        </tr>
      ))}
    </tbody>
  </table>
);
