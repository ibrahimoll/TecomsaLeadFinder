// People research state as the API reports it (CompanyDetail.people_research.state). The UI never infers it from
// several status fields, nor from an empty people list: zero people is a valid finished state.

export type PeopleResearchState =
  | "idle"
  | "website_queued"
  | "website_researching"
  | "deep_queued"
  | "deep_researching"
  | "completed"
  | "partial"
  | "failed"
  | "timed_out";

export interface PeopleResearch {
  state: PeopleResearchState;
  stage: "website" | "deep";
  website_status: string;
  external_status: string;
  people_count: number;
  finished_at: string | null;
  message: string | null;
  gap_reasons: string[];
}

export const POLL_MS = 3000;
export const SLOW_POLL_MS = 30000;
// Guardrail only: the backend finishes every stage at its own deadline (website ~2 min, deep ~3 min) plus queue
// wait. Past this, polling slows down and the page says so; it never hides a backend state.
export const POLL_LIMIT_MS = 6 * 60 * 1000;

const ACTIVE: PeopleResearchState[] = ["website_queued", "website_researching", "deep_queued", "deep_researching"];

export function isActive(state: PeopleResearchState | undefined): boolean {
  return !!state && ACTIVE.includes(state);
}

export function pollDelay(active: boolean, pollingForMs: number): number | null {
  if (!active) return null;
  return pollingForMs > POLL_LIMIT_MS ? SLOW_POLL_MS : POLL_MS;
}

export interface PeopleResearchView {
  active: boolean;
  badge: string | null; // live status next to the people (existing people always stay visible)
  emptyTitle: string; // the People tab with no one found
  note: string | null; // a finished state's caveat
}

export function researchView(research: PeopleResearch | null | undefined, hasPeople: boolean, overdue = false): PeopleResearchView {
  const state = research?.state ?? "idle";
  const active = isActive(state);
  if (active) {
    const badge = overdue
      ? "Research is taking longer than expected."
      : state.startsWith("deep")
        ? "Searching additional public sources…"
        : hasPeople
          ? "Refreshing public sources…"
          : "Searching company website…";
    return { active, badge, emptyTitle: badge, note: null };
  }
  const note =
    state === "partial"
      ? "Research completed with limited public-source coverage."
      : state === "failed"
        ? "Research could not be completed."
        : state === "timed_out"
          ? "Research reached its time limit. Existing verified results are shown."
          : null;
  return {
    active,
    badge: null,
    emptyTitle: state === "idle" ? "People research has not run yet." : "No verified people found from current public sources.",
    note,
  };
}
