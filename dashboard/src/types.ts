// Hand-written mirror of schemas/models.py (docs/traceability-matrix.schema.json) — only the fields the UI uses.
export type Band = "HIGH" | "AMBIGUOUS" | "LOW";
export type LinkKind = "implements" | "verifies" | "validates" | "mitigates";
export type Severity = "high" | "medium" | "low";

export interface Requirement { id: string; level: string; text: string; status: string; parent_id?: string | null; [k: string]: unknown }
export interface DesignOutput { id: string; title: string; artifact_path: string; [k: string]: unknown }
export interface Verification { id: string; method: string; result: string; [k: string]: unknown }
export interface Validation {
  id: string; source: string; evidence_id: string; model_id: string; overall_band: Band;
  requires_human_review: boolean; generated_at: string; summary: string; [k: string]: unknown;
}
export interface RiskControl { id: string; hazard: string; risk_index: number; [k: string]: unknown }
export interface Link { source_id: string; target_id: string; kind: LinkKind; confidence: number; band: Band; reasoning: string }
export interface Gap { item_id: string; kind: string; severity: Severity; band: Band; reasoning: string }
export interface Matrix {
  project_id: string;
  generated_at: string;
  requirements: Requirement[];
  design_outputs: DesignOutput[];
  verifications: Verification[];
  validations: Validation[];
  risk_controls: RiskControl[];
  links: Link[];
  gaps: Gap[];
  coverage: Record<string, number>;
  overall_band: Band;
  iec_62304_note: string;
  iso_14971_note: string;
}
