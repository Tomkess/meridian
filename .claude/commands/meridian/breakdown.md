---
model: claude-sonnet-5
---

Produce a technical decomposition of a feature.

$ARGUMENTS is the feature ID (e.g. `feat-007`). If omitted, ask which feature to break down.

This skill answers **how** to build it — architecture, components, data model, integration points.
It is distinct from `spec.md` (which answers *what* to build) and `tasks.md` (which lists atomic work units).

## Steps

**Do not read the design inputs into this thread.** Resolve their *paths* and hand those to the
design agent, which reads them itself. Reading them here means paying for the same corpus twice —
once in this context and again in the agent's — and this thread then carries it for the rest of
the session. See "Context discipline" below.

1. Resolve the feature directory: `specs/FEAT-NNN_*/`. Confirm `spec.md` exists.
2. Read **only the frontmatter** of `spec.md` to get `depends_on` (e.g.
   `sed -n '/^---$/,/^---$/p' specs/FEAT-NNN_*/spec.md`). Resolve each listed feature ID to its
   spec path. Do not read the bodies.
3. List (do not read) `specs/FEAT-NNN_*/summaries/`.
4. Note whether `specs/STEERING.md` and `specs/CONTRACT.md` exist.

5. Spawn a design agent to produce the breakdown:
   Use the Agent tool with `model: "opus"`. Pass it a prompt containing **paths, not contents**:
   - The path to this feature's `spec.md`
   - The paths of the summaries from step 3
   - The paths of the dependency specs from step 2
   - The path to `STEERING.md`, and to `CONTRACT.md` if it exists
   - The breakdown structure below (copy it verbatim into the prompt)

   Instruct the agent:
   > "You are a senior software architect. Read the files listed below, then produce a complete
   > Technical Breakdown following the exact structure given. Apply all STEERING.md constraints
   > and honour CONTRACT.md interfaces verbatim if it exists. Be concrete — name actual
   > components, fields, and integration points. No placeholder text.
   >
   > Working rules:
   > - Read each listed file **once**. Do not re-read a file you have already read.
   > - From a dependency spec, take only the Summary, Acceptance Criteria and any stated
   >   interfaces. Ignore its Risks, Open Questions and Related Research.
   > - Write the document in a **single** Write call. Do not read it back to verify. Do not make
   >   a revision pass — get it right the first time.
   > - Target 400–700 lines. If the design needs more, the feature is too large: say so in the
   >   effort estimate instead of writing more.
   > - Report back only: the file path, the line count, and any [DECISION NEEDED] items. Do not
   >   restate the breakdown's contents."

   Have the agent write directly to `specs/FEAT-NNN_*/breakdown.md`.
   Do not read the result back into this thread — the agent's summary is enough.

Breakdown structure — copy this verbatim into the agent's prompt:

---

## Technical Breakdown — FEAT-NNN: <name>

### Components
List each distinct component/module/service that needs to be built or modified.

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|

### Data Model
Any new tables, schemas, or data structures. Include field names and types.

### Integration Points
External systems, APIs, or other features this touches.

### Test Strategy
What needs to be tested and how (unit, integration, manual).

### Total Effort Estimate
Use the component effort scale below — this is **per-component** granularity, separate from
the feature-level `appetite` field in `spec.md` (xs/s/m/l).

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall:** M  *(replace with your estimate)*

<!-- C4: Component effort (S/M/L/XL) is finer-grained than spec appetite (xs/s/m/l).
     A feature with appetite "m" (1–2 weeks) may have one L component and several S ones. -->

### Implementation Order
Ordered list of components — what must be built first. This order feeds directly into `/tasks`.

---

After writing the file, the spec frontmatter `updated` date will be refreshed automatically
the next time a CLI command writes to it (e.g. when `/tasks` transitions status to `in-progress`).
**Do not edit frontmatter directly** — status transitions must go through the CLI so the registry
is rebuilt. C3: breakdown.md itself does not trigger a status change.

Confirm what was written, then suggest: "Run `/tasks FEAT-NNN` to generate the atomic task list."

## Context discipline

This skill spawns an Opus agent, which is the most expensive step in the Meridian pipeline. Three
rules keep it from costing multiples of what it should:

**Pass paths, never contents.** Inlining a spec into the agent prompt puts those bytes in *this*
thread as well, and this thread re-sends its whole context on every subsequent turn. The agent
reading the file itself costs one tool call and keeps this thread thin.

**Output is billed at roughly 5× input, and is never cached.** A 700-line breakdown is the single
largest charge in the run. A read-back-and-revise pass triples it for marginal gain. That is why
the agent is told to write once and not verify.

**Do not read the breakdown back here.** `/tasks` will read it in its own context. Pulling it into
this thread to "check it" doubles its cost and buys nothing.

### Running several features at once

Fan-out is fine — cost scales with *total tokens*, not with agent count. What makes a parallel run
expensive is each agent carrying a wide corpus through a long loop. So:

- Fan out **one stage at a time**: all specs, then review, then all breakdowns, then all tasks.
  A flawed spec caught here does not go on to fund a breakdown and a task list built on it.
- Give each agent only its own feature's inputs. If several features share interfaces, put those in
  `specs/CONTRACT.md` and pass that one path instead of upstream features' full documents.
- Launch fan-out from a **fresh, thin session**. The supervising thread's context is re-sent on
  every turn while it waits.
- Do not hand-roll parallel agents that do spec + breakdown + tasks in one loop. That carries the
  spec-stage corpus (VISION, goals, STEERING) all the way through the task stage, which needs none
  of it, and it bypasses the Sonnet pins on `/spec` and `/tasks`.
