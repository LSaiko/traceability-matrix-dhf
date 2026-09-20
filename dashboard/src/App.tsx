import { useEffect, useState } from "react";
import { load, type Data } from "./api";
import { Chip, CoverageTiles, EvidenceLog, GapTable, MatrixTable } from "./components";
import "./app.css";

export default function App() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    load().then(setData, (e) => setError(String(e)));
  }, []);
  if (error) return <main><p className="review">Failed to load: {error}</p></main>;
  if (!data) return <main><p className="muted">Loading...</p></main>;
  const m = data.matrix;
  return (
    <main>
      <header>
        <div>
          <h1>traceability-matrix-dhf</h1>
          <p className="muted">
            The Archivist: links DHF requirements to design outputs, V&amp;V evidence and ISO 14971 risk controls, and flags broken links by three-band confidence.
          </p>
          <p className="muted">
            project <code>{m.project_id}</code> · generated {m.generated_at.slice(0, 10)} · overall <Chip band={m.overall_band} /> · {m.links.length} links · {m.gaps.length} gaps · source: {data.source}
          </p>
        </div>
        <span className="badge">evidence only · human review required</span>
      </header>

      <section>
        <h2>Coverage</h2>
        <p className="muted">Share of approved requirements with a non-LOW link of each kind. LOW links are insufficient evidence and never count as coverage.</p>
        <CoverageTiles coverage={m.coverage} />
      </section>

      <section>
        <h2>Traceability matrix</h2>
        <p className="muted">Rows are design inputs (21 CFR 820.30(c)); each cell lists the records that trace to them with the link band (HIGH cyan, AMBIGUOUS orange, LOW slate). Hover a link for its confidence and reasoning.</p>
        <MatrixTable matrix={m} />
      </section>

      <section>
        <h2>Gap report</h2>
        <p className="muted">High severity first. The band is how confident the Archivist is that the gap is real; every gap needs a human disposition under 820.30(j).</p>
        <GapTable gaps={m.gaps} />
      </section>

      <section>
        <h2>Validation evidence log</h2>
        <p className="muted">ValidationEvidence packages ingested from ml-samd-validator; the link band follows the exporter's own drift band.</p>
        <EvidenceLog validations={m.validations} />
      </section>

      <section>
        <h2>Standards notes</h2>
        <p className="muted">{m.iec_62304_note}</p>
        <p className="muted">{m.iso_14971_note}</p>
      </section>
    </main>
  );
}
