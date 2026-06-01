import assert from "node:assert/strict";
import fs from "node:fs";

const html = fs.readFileSync("mtagentv2/index.html", "utf8");

assert.match(html, /function startRouteFirst/);
assert.match(html, /function generateInitialRoute/);
assert.match(html, /function replaceActiveStopWithPoi/);
assert.match(html, /function renderPlanRoute/);
assert.match(html, /currentRouteTripId/);
assert.match(html, /target_poi_id/);
assert.match(html, /decision_signals/);
assert.match(html, /decision_notes/);
assert.match(html, /ugcDecisionHtml/);
assert.match(html, /routeDecisionNoteHtml/);
assert.match(html, /route-decision-note/);
assert.match(html, /UGC/);
assert.match(html, /function renderPlanPoiLibrary/);
assert.match(html, /plan-library-card is-candidate/);
assert.match(html, /data-route-action="replace"/);
assert.match(html, /data-route-action="remove"/);
assert.match(html, /route-agent-note/);

const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
for (const script of scripts) {
  new Function(script);
}

console.log("mtagentv2 route-first smoke OK");
