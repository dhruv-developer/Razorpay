# Business Brain

A shared merchant world model for Razorpay: events go in, features and a state
vector come out, four specialist agents bid on what to do about it, a safety
kernel decides what may run unattended, and every step is recorded.

The admin console exposes all of it — analytics, the raw collections, the
decision pipeline, the audit trail, and a self-test suite that asserts real
invariants against live data.

## Run it

```bash
docker compose up --build
```

Web on http://localhost:3000, API on http://localhost:8000 (OpenAPI at `/docs`).
With `SEED_ON_START=true` the API generates a merchant with 21 days of traffic on
first boot and prints the login it created.

Running the pieces separately:

```bash
cd apps/api && uvicorn app.main:app --reload
```

```bash
cd apps/web && npm run dev
```

Both read from `.env` — copy `.env.example` and fill it in. Mongo and Redis must
be reachable; without Redis the system still runs and falls back to Mongo-only
deduplication, and the System page says so.

## The screens

**Merchant**

| Screen | What it answers |
|---|---|
| Overview | Is the business healthy right now, and where is cash heading? |
| Unresolved money | Which rupees have left a customer but are not usable cash yet? |
| Attention | What needs me, ranked by impact × urgency × confidence × reversibility? |
| Decisions | What does the brain recommend, why not the alternatives, and what did it actually achieve? |
| What if | Counterfactuals over the live state, including any action list you build. |
| Copilot | Grounded answers — the model words tool output and cannot move money. |

**Admin console**

| Screen | What it exposes |
|---|---|
| Analytics | GMV, success rate, method/channel splits, funnel, forecasts, agent leaderboard, outcome calibration, event volume, document counts |
| Agents & trust | Registry, capabilities, per-agent trust and calibration, the full proposal log, circuit breakers. Ask any agent for a live proposal |
| Decision pipeline | Recommendation → policy gate → approval → execution → verification → outcome, joined end to end |
| Events | The append-only ledger, filterable, plus an injector that runs the real ingestion path |
| Data explorer | Every merchant-scoped collection, searchable and paginated, with the full document behind each row |
| Audit trail | Who or what did each thing, and when |
| Policy & memory | Edit the reserve floor, approval ceilings, autonomy level and objective weights; store durable merchant memories |
| Test lab | Run the self-test suite; probe the policy gate and executor by hand |
| System | Dependency health, configuration, and per-collection storage |

## Testing

Everything is exercisable from the UI, and each entry point is a real code path —
nothing is mocked.

**Self-test suite** — *Admin → Test lab → Run self-test*, or:

```bash
curl -s -X POST localhost:8000/v1/admin/self-test \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"include_mutating": true}'
```

21 checks across storage, ingestion, features, state, anomaly, causal,
prediction, attention, money, simulation, agents, safety and copilot. Each one
asserts an invariant against your live data — that forecast bands are ordered
p10 ≤ p50 ≤ p90, that unresolved money reconciles to its buckets, that the kernel
rejects cross-merchant calls, that replaying an event id is deduplicated, that an
action's full lifecycle lands in the outcome ledger exactly once.

Checks are tagged `read`, `derive` or `mutate`. Write checks are off by default;
enabling them creates a harmless `observe` action, a rejected high-value refund
request, an orchestration run and one de-duplicated event.

**Other things you can drive by hand**

- *Events → Inject a test event* pushes an event through entity resolution,
  feature recompute and state recompute, and the numbers move immediately.
- *Test lab → Action probe* creates an action of any type and shows what the
  policy gate decided and why, then lets you approve or reject it.
- *Agents → Ask for a proposal* runs one agent against current state without
  creating anything.
- *What if → Custom scenario* simulates an arbitrary action list.
- *Policy* changes take effect on the next action the kernel evaluates; the risk
  ladder shows live which action types your current autonomy level allows.

## Design notes

Money is integer paise everywhere; rupees exist only at the display edge.
Timestamps are UTC end to end and are serialised with an explicit offset.

Charts follow one palette with a fixed categorical slot order, never two y-axes,
a legend whenever there are two or more series, and a table view on every chart
so no value is reachable only by hovering. Both light and dark palettes were
validated for colour-vision separation and contrast against the surfaces they
actually render on.
