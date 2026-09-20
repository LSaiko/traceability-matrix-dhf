import { seedMatrix } from "./seed";
import type { Matrix } from "./types";

const BASE = import.meta.env.VITE_API_BASE as string | undefined;
const PROJECT = (import.meta.env.VITE_PROJECT_ID as string | undefined) ?? seedMatrix.project_id;

export interface Data { matrix: Matrix; source: "api" | "seed" }

export async function load(): Promise<Data> {
  if (!BASE) return { matrix: seedMatrix, source: "seed" };
  const r = await fetch(`${BASE}/project/${PROJECT}/matrix`);
  if (!r.ok) throw new Error(`${r.status} /project/${PROJECT}/matrix`);
  return { matrix: (await r.json()) as Matrix, source: "api" };
}
