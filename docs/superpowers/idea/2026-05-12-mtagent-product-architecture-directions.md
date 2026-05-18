# mtagent Product & Architecture Directions

> Date: 2026-05-12
> Status: Brainstorm / direction alignment
> Scope: POI selection quality, route continuity, user adjustment, content research, agent orchestration, and persistent trip history.

## 1. Current Goal

mtagent should not only generate a list of POIs. It should generate a route that feels like a real local itinerary:

- The city essentials are not missed.
- The route does not jump around the city without reason.
- Different user types get different pacing and supporting stops.
- Users can reject a stop or a whole day without regenerating everything.
- Closing the browser does not lose an in-progress plan.
- Product research can be converted into concrete planning rules.

## 2. POI Data Direction

The POI pool should be modeled as three layers instead of one flat list.

### 2.1 City Essentials

Examples:

- Beijing: Forbidden City, Great Wall, Tiananmen
- Xi'an: Bell Tower, Giant Wild Goose Pagoda, Muslim Quarter
- Shanghai: The Bund, Yu Garden, Lujiazui
- Shenzhen: Shenzhen Bay Park, Window of the World, OCT/Happy Coast

These POIs should not be filtered out by persona rules. They are city backbone points.

Recommended fields:

```json
{
  "poi_role": "city_essential",
  "universal_level": "high",
  "must_consider": true,
  "constraints": {
    "queue_heavy": true,
    "walk_heavy": true,
    "requires_reservation": true
  }
}
```

Key rule:

> City essentials are baseline candidates. Persona changes how they are used, not whether they exist.

For example, Forbidden City can appear for all users, but the arrangement differs:

- Couple: Forbidden City + photo spot + atmospheric dinner
- Family: shorter route + indoor fallback + nearby meal
- Senior: lighter walking path + fewer transfers
- Friends: Forbidden City + nearby shopping/nightlife extension

### 2.2 Persona Preference POIs

These are POIs that are especially suitable for a specific user type.

Examples:

- Couple: photo-friendly, atmosphere, night view
- Family: kid-friendly, stroller-friendly, indoor fallback
- Senior: low walking burden, cultural, accessible
- Friends: lively, group-friendly, late-night options
- Business: efficient, near transport hubs, private rooms

This layer should use `persona_labels` and `modifiers`.

Existing related code:

- `scripts/label_pois.py`
- `data/poi_labels.json`
- `dianping/client.py`
- `agents/tools.py::route_by_persona`

Recommended improvement:

- Keep current automatic labeling.
- Add a manual correction list for important POIs.
- Avoid hard-filtering city essentials.

### 2.3 Filler / Connector POIs

These are not the main reason for the trip, but they make the route coherent.

Examples:

- Lunch / dinner
- Coffee / afternoon tea
- Mall / rest stop
- Night view
- Nearby casual activity

Their job is to connect the day:

- Fill meal slots.
- Reduce awkward transfers.
- Provide rest.
- Give a soft landing after a heavy attraction.

Key rule:

> Essentials define the skeleton, persona POIs add character, filler POIs make the day usable.

## 3. District Continuity

Large cities should be planned by districts or city blocks, but not with an absolute "same district only" rule.

The desired behavior is:

- One day should usually have one main district.
- Neighboring districts can be connected if the route is natural.
- Far district jumps require a strong reason.
- A sparse district can be used for one valuable anchor, then connected to a richer nearby area.

Example:

Shenzhen Bay Park -> Window of the World -> Futian can be acceptable because it has a directional flow.

But:

Bao'an morning -> Futian lunch -> Nanshan afternoon -> Bao'an night is likely tiring and incoherent.

Recommended route rules:

```text
same district: preferred
neighbor district: allowed
far district: only if POI is city_essential or user must_visit
cross-district count per day: usually <= 1
backtracking: avoid
```

Potential data fields:

```json
{
  "district": "Nanshan",
  "city_zone": "west",
  "neighbor_districts": ["Futian", "Bao'an"],
  "transfer_weight": 1.2
}
```

Planning implication:

- Cluster by geography first.
- Then route within the cluster.
- Allow controlled cross-zone bridges for high-value POIs.

## 4. Route Rendering & Map Quality

SSE and map rendering should not fake route quality.

Current risk:

- If AMap route search fails, the frontend may draw a straight line.
- The same polyline can be drawn once from `planner.day_done` and again after fetching the completed trip.

Desired behavior:

- Real route polyline is shown only when actual path points are available.
- If routing fails, show a "route unavailable" state instead of drawing a misleading straight line.
- Polyline rendering should have one owner to avoid duplicate lines.

Recommended direction:

- Backend persists `transit_segments`.
- Frontend renders route once per segment.
- `source = estimated` can be shown as an estimate, but not as a street-level route.

## 5. User Adjustment

Users need two adjustment levels.

### 5.1 Replace One Stop

Use when the user dislikes a single POI.

Behavior:

- Keep the same day.
- Keep the same slot.
- Search inside the same cluster or nearby district.
- Prefer same category or compatible role.
- Recompute only adjacent transit segments.

Example:

> "I don't like this museum, change one."

Only that stop changes. The rest of the route remains stable.

### 5.2 Redo One Day

Use when the user dislikes the entire day.

Behavior:

- Keep trip-level intent.
- Keep other days unchanged.
- Rebuild only the selected day.
- Avoid already rejected POIs.
- Recompute that day's transit segments.

Example:

> "Day 2 feels too tiring. Replan this day."

Only Day 2 changes.

Related existing schema:

- `Feedback.action = replace_stop | redo_day | mark_disliked | mark_been_there`
- `Adjuster` is currently a stub and should become the owner of this behavior.

Important requirement:

> The system needs to persist candidate pools or enough planning context, otherwise local adjustment will degrade into full regeneration.

## 6. Product Research Workstream

This is suitable for a product-oriented teammate.

The goal is not to scrape massive data. The goal is to extract accepted itinerary patterns from high-quality examples.

Recommended task scope:

- Collect 20-30 high-quality itinerary samples.
- Cover 3-5 cities if possible.
- Classify by user scenario: couple, family, senior, friends, solo.
- Summarize what makes an itinerary feel reasonable.

Expected output table:

| Scenario | Daily stop count | Meal placement | Walking tolerance | District rule | Good pattern | Bad pattern |
|---|---:|---|---|---|---|---|
| Couple photo trip | 4-5 | lunch near attraction, dinner with atmosphere | medium | 1 main district + night extension | landmark + photo spot + dinner | too many museums |
| Family trip | 3-4 | fixed meal/rest slots | low | same district preferred | indoor fallback + short transfers | long cross-city jumps |
| Senior trip | 3 | early start, long rest | low | same district strongly preferred | cultural anchor + nearby meal | backtracking |

How this research feeds engineering:

- Adjust `day_template`.
- Improve `poi_role` and manual labels.
- Add route rhythm rules.
- Improve rationale wording.
- Add demo examples that feel human.

## 7. Persistent Jobs, SSE, and Chat History

Important product principle:

> SSE is only a display channel. It should not be the planning task itself.

Problem:

If the browser is closed while `/api/plan/stream` is running, the connection may be cancelled and the user can lose progress.

Desired model:

```text
POST /api/trips
  -> create trip job
  -> return trip_id immediately

GET /api/trips/{trip_id}
  -> return current status and final route if completed

GET /api/trips/{trip_id}/events
  -> return persisted event history

GET /api/trips/{trip_id}/stream
  -> subscribe to live events

GET /api/conversations
  -> list previous conversations

GET /api/conversations/{conversation_id}
  -> restore messages, trip ids, summaries
```

Minimal storage for hackathon:

```text
data/conversations/{conversation_id}.json
data/trips/{trip_id}.json
data/trip_events/{trip_id}.jsonl
```

Future production storage:

- SQLite/Postgres for conversations and trips
- Redis or background worker queue for jobs
- resumable SSE via `Last-Event-ID`

Conversation model:

```text
Conversation
  conversation_id
  user_id / cookie_key
  title
  summary
  messages[]
  trip_ids[]

TripJob
  trip_id
  conversation_id
  status: queued / running / completed / failed
  user_input
  intent
  draft_route
  events[]
```

This enables:

- Browser close and reopen.
- History page.
- Replay previous generation events.
- Start a new conversation with summary from previous one.

## 8. Agent Orchestration

Recommended responsibility split:

```text
Profiler
  Understand user input.
  Extract city, days, traveler_type, budget, pace, preferences, must_visit, avoid.

Planner
  Build candidate pools.
  Combine city essentials, persona POIs, and filler POIs.
  Plan by district continuity.
  Produce day plans and transit segments.

Critic
  Validate route quality.
  Check business hours, excessive travel, duplicate POIs, backtracking, bad district jumps.
  Output patches or warnings.

Adjuster
  Handle replace_stop and redo_day.
  Persist user dislikes and been-there signals.
  Recompute only affected route parts.

Labeler / Research Pipeline
  Offline POI tagging.
  Manual city essential list.
  Research-derived route templates.
```

Avoid adding too many new agents too early. Most quality gains should come from stronger data structures and deterministic planning rules.

## 9. Suggested Priority

### P0: Make POI Data Smarter

- Add `poi_role`.
- Add `city_essential` list per city.
- Prevent city essentials from being removed by persona filtering.
- Add manual labels for top POIs.

### P1: Make Routes Less Awkward

- Add district/zone metadata.
- Penalize unnecessary cross-district movement.
- Allow high-value cross-district anchors.
- Avoid backtracking.

### P2: Fix Map Trust

- Avoid duplicate polyline rendering.
- Do not draw straight-line fallback as if it were a real route.
- Show route unavailable or estimated state when path search fails.

### P3: Add Adjustment Loop

- Implement `replace_stop`.
- Implement `redo_day`.
- Persist user feedback.

### P4: Add Persistent Conversation / Job Model

- Decouple job execution from SSE connection.
- Persist event history.
- Restore trip history and chat records.

### P5: Product Research Integration

- Convert teammate's research into route templates and scoring rules.
- Use findings to improve default pacing and rationale.

## 10. One-Sentence Product Logic

City essentials are the skeleton, persona POIs are the character, filler POIs are the glue, district continuity is the comfort, and SSE/chat persistence is what makes the product reliable.
