// Self-check of the People-tab state logic: node lib/people-research.check.mjs (Node >= 22.18 strips TS types).
import assert from "node:assert/strict";
import { POLL_LIMIT_MS, POLL_MS, SLOW_POLL_MS, isActive, pollDelay, researchView } from "./people-research.ts";

const r = (state) => ({ state, stage: "deep", website_status: "completed", external_status: state, people_count: 0,
  finished_at: null, message: null, gap_reasons: [] });

// polling stops on every final state, and zero people is never "still searching"
for (const s of ["completed", "partial", "failed", "timed_out", "idle"]) {
  assert.equal(isActive(s), false, s);
  assert.equal(pollDelay(isActive(s), 0), null, s);
  assert.equal(researchView(r(s), false).active, false, s);
  assert.equal(researchView(r(s), false).badge, null, s);
}
assert.equal(researchView(r("completed"), false).emptyTitle, "No verified people found from current public sources.");
assert.equal(researchView(r("partial"), false).note, "Research completed with limited public-source coverage.");
assert.equal(researchView(r("failed"), false).note, "Research could not be completed.");
assert.match(researchView(r("timed_out"), true).note, /time limit/);

// active states poll; the guardrail slows polling and says so
for (const s of ["website_queued", "website_researching", "deep_queued", "deep_researching"]) {
  assert.equal(pollDelay(isActive(s), 0), POLL_MS, s);
  assert.equal(pollDelay(isActive(s), POLL_LIMIT_MS + 1), SLOW_POLL_MS, s);
}
assert.equal(researchView(r("website_researching"), false).badge, "Searching company website…");
assert.equal(researchView(r("deep_queued"), false).badge, "Searching additional public sources…");
assert.equal(researchView(r("deep_researching"), true, true).badge, "Research is taking longer than expected.");
// existing people stay visible during a refresh: a separate indicator, not an empty tab
assert.equal(researchView(r("website_researching"), true).badge, "Refreshing public sources…");
console.log("people-research: ok");
