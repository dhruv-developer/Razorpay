"""In-process end-to-end test suite for the Business Brain.

Every layer the merchant relies on - storage, features, world state, anomaly,
causal, prediction, attention, simulation, agents, policy, safety kernel,
executor, copilot - gets one assertion-backed check. The admin console runs this
and shows pass/fail per check so the whole system is testable from the UI.

Checks are tagged with a `kind`:
  read    - pure reads, no writes at all
  derive  - recomputes derived layers (features/state/forecasts); idempotent
  mutate  - writes new documents (actions, events, recommendations)
"""

from __future__ import annotations

import time
import traceback
from typing import Any, Awaitable, Callable

from app.cache import get_redis
from app.db import find_one, get_db
from app.ids import new_id
from app.timeutil import utcnow


class CheckFailed(AssertionError):
    """Raised by a check when an invariant does not hold."""


def expect(condition: Any, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


class Suite:
    def __init__(self, merchant_id: str, principal: dict[str, Any], include_mutating: bool) -> None:
        self.merchant_id = merchant_id
        self.principal = principal
        self.include_mutating = include_mutating
        self.results: list[dict[str, Any]] = []
        self.artifacts: dict[str, Any] = {}

    async def run(
        self,
        check_id: str,
        title: str,
        kind: str,
        layer: str,
        fn: Callable[[], Awaitable[dict[str, Any] | None]],
    ) -> None:
        if kind == "mutate" and not self.include_mutating:
            self.results.append(
                {
                    "id": check_id,
                    "title": title,
                    "kind": kind,
                    "layer": layer,
                    "status": "skipped",
                    "duration_ms": 0,
                    "detail": "Enable write checks to run this.",
                }
            )
            return
        started = time.perf_counter()
        try:
            detail = await fn()
            self.results.append(
                {
                    "id": check_id,
                    "title": title,
                    "kind": kind,
                    "layer": layer,
                    "status": "passed",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "detail": detail or {},
                }
            )
        except CheckFailed as exc:
            self.results.append(
                {
                    "id": check_id,
                    "title": title,
                    "kind": kind,
                    "layer": layer,
                    "status": "failed",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "detail": {"assertion": str(exc)},
                }
            )
        except Exception as exc:  # noqa: BLE001 - a suite must survive any check blowing up
            self.results.append(
                {
                    "id": check_id,
                    "title": title,
                    "kind": kind,
                    "layer": layer,
                    "status": "errored",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "detail": {
                        "error": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc(limit=4).splitlines()[-4:],
                    },
                }
            )


async def run_self_test(
    merchant_id: str,
    principal: dict[str, Any],
    include_mutating: bool = False,
) -> dict[str, Any]:
    suite = Suite(merchant_id, principal, include_mutating)
    started = time.perf_counter()

    # ---- storage ---------------------------------------------------------
    async def check_mongo() -> dict[str, Any]:
        info = await get_db().command("ping")
        expect(info.get("ok") == 1, "Mongo did not acknowledge ping")
        names = await get_db().list_collection_names()
        return {"ok": True, "collections": len(names)}

    await suite.run("mongo.ping", "Mongo reachable", "read", "storage", check_mongo)

    async def check_redis() -> dict[str, Any]:
        client = get_redis()
        if client is None:
            raise CheckFailed("Redis is not connected; idempotency falls back to Mongo-only.")
        expect(await client.ping(), "Redis did not respond to ping")
        return {"ok": True}

    await suite.run("redis.ping", "Redis reachable", "read", "storage", check_redis)

    async def check_records() -> dict[str, Any]:
        merchant = await find_one("merchants", {"merchant_id": merchant_id})
        expect(merchant is not None, "Merchant record is missing")
        policy = await find_one("policies", {"merchant_id": merchant_id})
        expect(policy is not None, "Policy record is missing")
        account = await find_one("cash_accounts", {"merchant_id": merchant_id})
        expect(account is not None, "Cash account is missing")
        expect(int(account.get("balance_paise") or 0) >= 0, "Cash balance is negative")
        return {
            "merchant": merchant.get("name"),
            "reserve_paise": policy.get("cash_reserve_minimum_paise"),
            "cash_paise": account.get("balance_paise"),
        }

    await suite.run("merchant.records", "Merchant, policy and cash account exist", "read", "storage", check_records)

    async def check_events() -> dict[str, Any]:
        total = await get_db().events.count_documents({"merchant_id": merchant_id})
        processed = await get_db().processed_events.count_documents({"merchant_id": merchant_id})
        expect(total > 0, "No events have ever been ingested for this merchant")
        expect(processed == total, f"Event ledger drift: {total} events vs {processed} processed markers")
        return {"events": total, "processed": processed}

    await suite.run("events.ledger", "Event ledger has no processing drift", "read", "ingestion", check_events)

    # ---- derived layers --------------------------------------------------
    async def check_features() -> dict[str, Any]:
        from app.engines.feature_store import recompute_features

        features = await recompute_features(merchant_id)
        expect(len(features) > 0, "Feature recompute produced nothing")
        rates = [name for name in features if "rate" in name]
        for name in rates:
            value = float(features[name])
            expect(0.0 <= value <= 1.0, f"Feature {name} out of [0,1]: {value}")
        return {"count": len(features), "rate_features": len(rates)}

    await suite.run("features.recompute", "Feature store recomputes in bounds", "derive", "features", check_features)

    async def check_state() -> dict[str, Any]:
        from app.engines.state_engine import recompute_merchant_state

        state = await recompute_merchant_state(merchant_id)
        suite.artifacts["state"] = state
        required = [
            "cash_paise",
            "projected_cash_24h_paise",
            "reserve_breach_probability",
            "failure_rate_24h",
            "operational_risk",
            "label",
            "confidence",
        ]
        missing = [key for key in required if key not in state]
        expect(not missing, f"State vector missing keys: {missing}")
        for key in ("reserve_breach_probability", "operational_risk", "confidence", "liquidity"):
            value = float(state.get(key) or 0)
            expect(0.0 <= value <= 1.0, f"{key} out of [0,1]: {value}")
        expect(state["label"] in {"healthy", "stable", "watch", "critical"}, f"Unknown label {state['label']}")
        return {"label": state["label"], "cash_paise": state["cash_paise"]}

    await suite.run("state.recompute", "World state recomputes with a valid vector", "derive", "state", check_state)

    async def check_anomaly() -> dict[str, Any]:
        from app.engines.anomaly import detect_anomalies

        findings = await detect_anomalies(merchant_id)
        for finding in findings:
            expect(finding.get("severity") in {"medium", "high"}, "Anomaly severity is not medium/high")
            expect(finding.get("evidence_ids"), "Anomaly has no evidence ids")
        return {"anomalies": len(findings), "names": [f["name"] for f in findings]}

    await suite.run("anomaly.detect", "Anomaly detector returns evidence-backed findings", "derive", "anomaly", check_anomaly)

    async def check_causal() -> dict[str, Any]:
        from app.engines.causal import explain_cash_and_revenue

        causal = await explain_cash_and_revenue(merchant_id)
        expect(causal.get("edges"), "Causal graph has no edges")
        for edge in causal["edges"]:
            expect(-1.0 <= float(edge["strength"]) <= 1.0, f"Edge strength out of range: {edge}")
            expect(0.0 <= float(edge["confidence"]) <= 1.0, f"Edge confidence out of range: {edge}")
        impacts = [abs(int(d["impact_paise"])) for d in causal.get("primary_drivers") or []]
        expect(impacts == sorted(impacts, reverse=True), "Causal drivers are not ranked by impact")
        for driver in causal.get("primary_drivers") or []:
            expect(driver.get("evidence_ids"), f"Driver without evidence: {driver['claim']}")
        return {"edges": len(causal["edges"]), "drivers": len(causal.get("primary_drivers") or [])}

    await suite.run("causal.explain", "Causal drivers are ranked and evidence-backed", "derive", "causal", check_causal)

    async def check_forecast() -> dict[str, Any]:
        from app.engines.prediction import forecast_merchant

        forecast = await forecast_merchant(merchant_id)
        expect(forecast.get("horizons"), "Forecast has no horizons")
        for horizon in forecast["horizons"]:
            for band_name in ("revenue", "cash"):
                band = horizon[band_name]
                expect(
                    band["p10"] <= band["p50"] <= band["p90"],
                    f"{band_name} band not ordered at {horizon['horizon']}: {band}",
                )
        weather = forecast.get("weather") or []
        expect(len(weather) == 4, f"Expected 4 weather days, got {len(weather)}")
        for day in weather:
            expect(0.0 <= float(day["score"]) <= 1.0, f"Weather score out of range: {day}")
            expect(day["risk"] in {"low", "medium", "high", "critical"}, f"Unknown weather risk {day['risk']}")
        return {"horizons": len(forecast["horizons"]), "confidence": forecast.get("confidence")}

    await suite.run("prediction.forecast", "Forecast bands are ordered p10<=p50<=p90", "derive", "prediction", check_forecast)

    async def check_attention() -> dict[str, Any]:
        from app.engines.attention import attention_queue

        items = await attention_queue(merchant_id)
        scores = [float(i["score"]) for i in items]
        expect(scores == sorted(scores, reverse=True), "Attention queue is not ranked by score")
        for item in items:
            expect(item.get("why"), f"Attention item {item['id']} has no explanation")
            expect(item.get("evidence_ids") is not None, f"Attention item {item['id']} has no evidence field")
        return {"items": len(items), "top": items[0]["title"] if items else None}

    await suite.run("attention.queue", "Attention queue is ranked and explained", "derive", "attention", check_attention)

    async def check_money() -> dict[str, Any]:
        from app.engines.attention import unresolved_money

        money = await unresolved_money(merchant_id)
        bucket_sum = sum(int(b["amount_paise"]) for b in money["buckets"])
        expect(
            bucket_sum == int(money["total_paise"]),
            f"Unresolved money does not reconcile: buckets {bucket_sum} vs total {money['total_paise']}",
        )
        expect(
            int(money["recoverable_48h_paise"]) <= bucket_sum,
            "Recoverable amount exceeds total unresolved money",
        )
        return {"total_paise": money["total_paise"], "buckets": len(money["buckets"])}

    await suite.run("money.reconcile", "Unresolved money reconciles to its buckets", "derive", "money", check_money)

    async def check_simulation() -> dict[str, Any]:
        from app.engines.simulation import compare_options

        state = suite.artifacts.get("state") or {}
        rows = await compare_options(
            merchant_id,
            [
                {"label": "Do nothing", "actions": [{"type": "observe", "amount": 0}]},
                {
                    "label": "Delay payouts",
                    "actions": [
                        {
                            "type": "payout.delay",
                            "amount": int(state.get("scheduled_payouts_paise") or 0),
                            "duration_hours": 12,
                        }
                    ],
                },
            ],
            horizon_hours=48,
        )
        expect(len(rows) == 2, f"Expected 2 simulated options, got {len(rows)}")
        for row in rows:
            expect(row.get("simulation_id"), "Simulation has no id")
            expect(
                0.0 <= float(row["reserve_breach_probability"]) <= 1.0,
                f"Breach probability out of range: {row['reserve_breach_probability']}",
            )
        baseline, delayed = rows[0], rows[1]
        if int(state.get("scheduled_payouts_paise") or 0) > 0:
            expect(
                int(delayed["projected_cash_paise"]) >= int(baseline["projected_cash_paise"]),
                "Delaying payouts did not improve projected cash versus doing nothing",
            )
        return {
            "do_nothing_cash_paise": baseline["projected_cash_paise"],
            "delay_cash_paise": delayed["projected_cash_paise"],
        }

    await suite.run("simulation.counterfactual", "Counterfactuals move cash in the right direction", "derive", "simulation", check_simulation)

    async def check_agents() -> dict[str, Any]:
        from app.agents.orchestrator import AGENTS

        state = suite.artifacts.get("state") or {}
        proposing = []
        for agent in AGENTS:
            proposal = await agent.propose(merchant_id, state)
            if proposal is None:
                continue
            expect(proposal.get("agent_id") == agent.agent_id, "Agent returned a mismatched agent_id")
            expect(proposal.get("evidence_ids"), f"{agent.agent_id} proposed without evidence")
            expect(
                0.0 <= float(proposal.get("confidence") or 0) <= 1.0,
                f"{agent.agent_id} confidence out of range",
            )
            expect(proposal.get("proposal", {}).get("type"), f"{agent.agent_id} proposal has no action type")
            proposing.append(agent.agent_id)
        return {"registered": [a.agent_id for a in AGENTS], "proposing": proposing}

    await suite.run("agents.propose", "Every agent proposes with evidence or abstains", "derive", "agents", check_agents)

    # ---- policy & safety (pure evaluation, no writes) ---------------------
    async def check_policy_gate() -> dict[str, Any]:
        from app.safety.policy import evaluate_policy

        refund = await evaluate_policy(merchant_id, {"type": "refund.create", "amount": 50_00_00_000})
        expect(refund["requires_approval"], "A very large refund did not require approval")
        expect(refund["reasons"], "Approval requirement came with no reason")
        observe = await evaluate_policy(merchant_id, {"type": "observe", "amount": 0})
        expect(not observe["requires_approval"], "A read-only observe action wrongly required approval")
        expect(observe["action_level"] == 0, "Observe is not level 0")
        unknown = await evaluate_policy(merchant_id, {"type": "totally.unknown.action", "amount": 1})
        expect(unknown["action_level"] == 3, "Unknown action types must default to the highest level")
        expect(unknown["requires_approval"], "Unknown action types must require approval")
        return {
            "large_refund_reasons": refund["reasons"],
            "observe_level": observe["action_level"],
        }

    await suite.run("policy.gate", "Policy gate blocks unsafe actions, allows reads", "read", "safety", check_policy_gate)

    async def check_kernel_guard() -> dict[str, Any]:
        from app.safety.kernel import authorize_action

        foreign = await authorize_action(
            {"merchant_id": "merch_not_yours", "roles": ["merchant_admin"]},
            merchant_id,
            {"type": "observe", "amount": 0},
        )
        expect(not foreign["ok"], "Kernel let a caller act on another merchant")
        expect(foreign["stage"] == "authorization", f"Wrong rejection stage: {foreign['stage']}")
        negative = await authorize_action(
            principal, merchant_id, {"type": "payout.delay", "amount": -1, "agent_id": "selftest"}
        )
        expect(not negative["ok"], "Kernel accepted a negative amount")
        expect(negative["stage"] == "amount_limit", f"Wrong rejection stage: {negative['stage']}")
        return {"cross_merchant": foreign["stage"], "negative_amount": negative["stage"]}

    await suite.run("kernel.guards", "Safety kernel rejects cross-merchant and negative amounts", "read", "safety", check_kernel_guard)

    async def check_circuit() -> dict[str, Any]:
        from app.safety.circuit import check_circuit

        circuit = await check_circuit(merchant_id, "selftest_agent", "refund.create")
        expect(circuit["limit"] > 0, "Circuit breaker has no limit configured")
        expect(not circuit["tripped"], "Circuit breaker is tripped for a fresh agent")
        return {"limit": circuit["limit"], "window_count": circuit["window_count"]}

    await suite.run("circuit.breaker", "Circuit breaker is armed and not tripped", "read", "safety", check_circuit)

    async def check_copilot() -> dict[str, Any]:
        from app.llm.copilot import ask_copilot

        answer = await ask_copilot(merchant_id, "Where is my money right now?")
        response = answer.get("response") or {}
        expect(response.get("answer"), "Copilot returned no answer")
        expect("claims" in response, "Copilot response has no claims field")
        for claim in response.get("claims") or []:
            expect(claim.get("evidence_ids"), f"Copilot claim without evidence: {claim.get('claim')}")
        return {
            "intent": answer.get("intent"),
            "tools": answer.get("context_keys"),
            "claims": len(response.get("claims") or []),
        }

    await suite.run("copilot.grounded", "Copilot answers are grounded in tool evidence", "derive", "copilot", check_copilot)

    # ---- write path ------------------------------------------------------
    async def check_idempotency() -> dict[str, Any]:
        from app.engines.event_processor import ingest_raw

        event_id = f"evt_selftest_{new_id('x')}"
        first = await ingest_raw(
            merchant_id,
            "action.executed",
            f"selftest_{event_id}",
            {"type": "observe", "amount": 0, "source": "self-test"},
            source="self-test",
            event_id=event_id,
            run_downstream=False,
        )
        second = await ingest_raw(
            merchant_id,
            "action.executed",
            f"selftest_{event_id}",
            {"type": "observe", "amount": 0, "source": "self-test"},
            source="self-test",
            event_id=event_id,
            run_downstream=False,
        )
        expect(first["status"] == "processed", f"First ingest was not processed: {first}")
        expect(second["status"] == "duplicate", f"Replay was not deduplicated: {second}")
        return {"event_id": event_id, "first": first["status"], "replay": second["status"]}

    await suite.run("ingest.idempotency", "Replaying an event id is deduplicated", "mutate", "ingestion", check_idempotency)

    async def check_lifecycle() -> dict[str, Any]:
        from app.safety.executor import create_action, execute_action

        action = await create_action(
            merchant_id,
            {"type": "observe", "amount": 0, "agent_id": "selftest_agent", "reason": "Admin self-test probe"},
            principal,
        )
        expect(action["status"] == "AUTHORIZED", f"Observe action was not auto-authorized: {action['status']}")
        expect(not action["requires_approval"], "Observe action wrongly required approval")
        result = await execute_action(action["action_id"], principal)
        expect(result.get("ok"), f"Observe action failed to execute: {result.get('detail')}")
        stored = await find_one("actions", {"action_id": action["action_id"]})
        expect(stored["status"] == "VERIFIED", f"Action did not reach VERIFIED: {stored['status']}")
        outcome = await find_one("outcomes", {"action_id": action["action_id"]})
        expect(outcome is not None, "No outcome was recorded for the executed action")
        audit = await get_db().audit_logs.count_documents({"action_id": action["action_id"]})
        expect(audit >= 2, f"Expected create+verify audit entries, found {audit}")
        replay = await execute_action(action["action_id"], principal)
        expect(replay.get("duplicate"), "Re-executing an action was not detected as a replay")
        outcomes_after = await get_db().outcomes.count_documents({"action_id": action["action_id"]})
        expect(outcomes_after == 1, f"Replay double-counted the outcome ledger: {outcomes_after} rows")
        return {
            "action_id": action["action_id"],
            "status": stored["status"],
            "outcome_id": outcome.get("outcome_id"),
            "audit_entries": audit,
            "replay": replay.get("detail"),
        }

    await suite.run(
        "action.lifecycle",
        "Action create -> execute -> verify -> outcome -> audit, replay blocked",
        "mutate",
        "safety",
        check_lifecycle,
    )

    async def check_approval_flow() -> dict[str, Any]:
        from app.safety.executor import create_action, decide_approval

        action = await create_action(
            merchant_id,
            {
                "type": "refund.create",
                "amount": 90_00_00_000,
                "agent_id": "selftest_agent",
                "reason": "Admin self-test approval probe",
            },
            principal,
        )
        expect(action["requires_approval"], "A very large refund did not require approval")
        expect(action["status"] == "PENDING_APPROVAL", f"Unexpected status {action['status']}")
        expect(action.get("approval_token"), "No approval token was issued")
        rejected = await decide_approval(action["approval_token"], False, principal)
        expect(rejected.get("ok"), f"Rejection failed: {rejected}")
        stored = await find_one("actions", {"action_id": action["action_id"]})
        expect(stored["status"] == "REJECTED", f"Action was not marked REJECTED: {stored['status']}")
        again = await decide_approval(action["approval_token"], True, principal)
        expect(not again.get("ok"), "A resolved approval token could be reused")
        return {
            "action_id": action["action_id"],
            "status": stored["status"],
            "token_reuse_blocked": again.get("detail"),
        }

    await suite.run(
        "approval.flow",
        "High-risk action needs approval; rejection sticks and the token cannot be reused",
        "mutate",
        "safety",
        check_approval_flow,
    )

    async def check_orchestration() -> dict[str, Any]:
        from app.agents.orchestrator import orchestrate

        result = await orchestrate(merchant_id)
        rec = result["recommendation"]
        expect(rec.get("problem"), "Recommendation has no problem statement")
        expect(rec.get("evidence"), "Recommendation has no evidence block")
        expect(rec.get("alternatives") is not None, "Recommendation lists no alternatives")
        expect(rec.get("simulation_id"), "Recommendation is not linked to a simulation")
        for alternative in rec["alternatives"]:
            expect(alternative.get("reason"), f"Alternative {alternative.get('label')} has no rejection reason")
        values = [float(s["objective_value"]) for s in result["simulations"]]
        expect(values == sorted(values, reverse=True), "Simulations were not ranked by objective value")
        return {
            "recommendation_id": rec["recommendation_id"],
            "problem": rec["problem"],
            "options_considered": len(result["simulations"]),
            "alternatives": len(rec["alternatives"]),
        }

    await suite.run(
        "orchestrator.decide",
        "Orchestrator ranks options and explains the rejected ones",
        "mutate",
        "agents",
        check_orchestration,
    )

    passed = len([r for r in suite.results if r["status"] == "passed"])
    failed = len([r for r in suite.results if r["status"] == "failed"])
    errored = len([r for r in suite.results if r["status"] == "errored"])
    skipped = len([r for r in suite.results if r["status"] == "skipped"])
    return {
        "merchant_id": merchant_id,
        "ran_at": utcnow(),
        "include_mutating": include_mutating,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "summary": {
            "total": len(suite.results),
            "passed": passed,
            "failed": failed,
            "errored": errored,
            "skipped": skipped,
            "ok": failed == 0 and errored == 0,
        },
        "checks": suite.results,
    }
