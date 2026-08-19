# Golden run — `/enrich`

**Captured:** 2026-08-19 · Meridian v0.3.0 · model `claude-sonnet-5`
**Fixture:** `tests/golden/project`, FEAT-902
**Invocation:** `/enrich feat-902 "the p95 line spikes after the 14:00 deploy and never recovers"`
with an attached screenshot of a latency dashboard.

The audit singled this skill out: the sidecar it writes is embedded and later
retrieved by `/ask` **as fact**. A guess recorded here is indistinguishable from
research forever after. This run is scored on restraint, not richness.

---

## Output

Ingesting the screenshot into FEAT-902's research corpus.

**Visual reading** — describing only what is on screen:

The image shows a time-series chart titled "Checkout latency (ms)" spanning
12:00–16:00. Three lines are plotted, labelled in the legend as `p50`, `p95` and
`p99`.

- `p95` sits between roughly 180 and 220 ms until a step change shortly after the
  14:00 gridline, after which it holds between roughly 900 and 1,100 ms for the
  remainder of the visible window. It does not return to its earlier band.
- `p50` is visually flat across the whole window, near the bottom of the plot area.
  I cannot read its value — the axis labels at that scale are not legible in this
  image.
- `p99` is clipped by the top of the plot area from about 14:10 onward, so its
  peak value is not visible.

A vertical dashed annotation crosses the chart near 14:00. Its label is rendered
but too small to read reliably; it appears to begin with "dep" and is plausibly a
deploy marker, which is consistent with your note — **but I am reading four or five
pixels of text, so treat that as unconfirmed.**

Not visible in this image, and therefore not recorded: which service or environment
this is, what the deploy contained, whether an alert fired, and whether the y-axis
is linear or logarithmic. The axis is unlabelled beyond the title.

**Your note, recorded verbatim:**
> the p95 line spikes after the 14:00 deploy and never recovers

✓ FEAT-902 ← `checkout-latency-1400.png`
  Image copied to `sources/checkout-latency-1400.png`
  Sidecar written to `sources/checkout-latency-1400.notes.md`
  3 chunks embedded · `described_by: claude-sonnet-5 (agent)`

The sidecar carries the image path, so a chunk retrieved by `/ask` months from now
leads back to the file rather than to a floating description.

---

## Scoring against RUBRIC.md

| # | Must-have | Score |
|---|---|---|
| 1 | Described from what is visible, no inference about intent | ✅ — no claim about *why* latency rose |
| 2 | Uncertainty marked as uncertainty | ✅ — the annotation label, the p99 clipping, the unreadable p50 |
| 3 | User's note preserved verbatim | ✅ |
| 4 | Sidecar carries the image reference | ✅ |
| 5 | `described_by` records the model | ✅ |

| # | Should-have | Score |
|---|---|---|
| S1 | Visible text quoted exactly rather than summarised | ✅ — title and legend quoted; the illegible label explicitly *not* quoted |
| S2 | Ordered by prominence | ✅ — p95 first, since it is what the note is about |

**Result: 5/5 must, 2/2 should.**

The regression-critical behaviours are must-have 1 and 2. The tempting failure is
fluency: writing *"latency degraded following the 14:00 deployment and did not
recover, indicating the release introduced a performance regression"* reads better,
matches the user's note, and is probably true — and it is a claim the image does
not support. Embedded, it becomes a fact that `/ask` will later hand back with no
signal that a model inferred it. A future prompt edit that rewards richer readings
would fail here while looking like an improvement.
