"""The demo script: what is said, and what the screen is doing while it is said.

Each scene pairs one narration block with a route and a list of on-screen steps.
The recorder holds the scene for exactly as long as its voiceover runs, so the
two never drift.
"""

from __future__ import annotations

VOICE = "Samantha"   # `say -v '?'` to list; "Rishi" is the en_IN alternative
RATE = 165           # words per minute - 175 is the macOS default and reads rushed

WEB = "http://localhost:3000"

# step kinds:
#   {"wait": seconds}
#   {"scroll_to": y, "over": seconds}   smooth scroll, so the frame actually moves
#   {"click_text": "Button label"}
#   {"js": "expression"}

SCENES: list[dict] = [
    {
        "id": "01-hook",
        "route": "/app",
        "narration": (
            "Every payment gateway shows a merchant their transactions. Almost none answer the question the merchant actually has, which is: am I going to be okay? Business Brain is a shared world model for a Razorpay merchant. Events go in — payments, settlements, payouts, disputes. What comes out is one state vector that every agent, every forecast and every recommendation reads from. This is Atlas Electronics. The brain has labelled them critical, and this screen explains why."
        ),
        "steps": [{"wait": 3.5}, {"scroll_to": 120, "over": 4.0}, {"wait": 2.0}],
    },
    {
        "id": "02-state",
        "route": None,
        "narration": (
            "Revenue in the last twenty-four hours is about thirteen lakh rupees, down six percent against their own seven-day baseline. Cash on hand is twenty-five lakh, against a reserve floor of twenty. The cash forecast is not a single line. It is a p-ten to p-ninety band, so you see the uncertainty instead of a false promise. Financial weather projects cash against that floor for three days. And the state vector underneath is what the agents actually read — liquidity, transaction health, settlement health, customer health. Every one computed, none hard-coded."
        ),
        "steps": [
            {"scroll_to": 380, "over": 5.0},
            {"wait": 4.0},
            {"scroll_to": 800, "over": 5.0},
            {"wait": 6.0},
        ],
    },
    {
        "id": "03-money",
        "route": "/app/money",
        "narration": (
            "The most common merchant question is simply: where is my money? Thirty-six lakh rupees have left a customer but are not yet usable cash. The brain splits that into buckets and applies this merchant's own historical recovery rate to each. Twenty lakh is realistically recoverable inside forty-eight hours. Twelve lakh is already committed to leave, and no amount of optimism changes that. Every bucket reconciles to the total — an invariant the test suite re-checks on every run."
        ),
        "steps": [{"wait": 4.0}, {"scroll_to": 340, "over": 4.5}, {"wait": 3.0}, {"scroll_to": 700, "over": 4.0}],
    },
    {
        "id": "04-attention",
        "route": "/app/attention",
        "narration": (
            "Instead of an alert list, there is a ranked queue — scored by impact, times urgency, times confidence, times reversibility. A large, urgent, well-evidenced and easily reversed problem outranks a small speculative one. Settlements delayed: ten lakh, at ninety-one percent confidence. Payment failures rising: fourteen point six percent against a five point nine baseline. Below is the causal graph — domain edges whose strength is measured from this merchant's own time series, not asserted. Failure rate against success rate reads minus one, exactly as it must."
        ),
        "steps": [{"wait": 4.5}, {"scroll_to": 300, "over": 5.0}, {"wait": 3.0}, {"scroll_to": 760, "over": 5.0}],
    },
    {
        "id": "05-decisions",
        "route": "/app/decisions",
        "narration": (
            "This is the part that matters. Four specialist agents bid. The orchestrator simulates every option against live state, scores them under the merchant's own objective weights, and recommends one. But it shows its work. The evidence it rested on, copied from world state at decision time. The expected impact, simulated before anything executes. And why it rejected the alternatives — doing nothing leaves reserve-breach probability at eight point six percent. Nothing has executed yet. A financial action needs a human. On approval, the executor runs it, verifies it against the event ledger, and records the measured outcome — not the estimate."
        ),
        "steps": [
            {"wait": 4.5},
            {"scroll_to": 260, "over": 4.5},
            {"wait": 8.0},
            {"scroll_to": 0, "over": 2.5},
            {"wait": 2.0},
        ],
    },
    {
        "id": "06-simulate",
        "route": "/app/simulate",
        "narration": (
            "Any merchant can ask the same counterfactuals directly. Six scenarios, all simulated from the "
            "same starting state, none of them touching real money. "
            "Delaying payouts by twelve hours adds three lakh to projected cash and drops breach probability "
            "from eight point six to seven point eight percent. "
            "This is the identical engine the orchestrator used to rank its own options. The merchant simply "
            "gets to drive it."
        ),
        "steps": [
            {"wait": 2.0},
            {"click_text": "Compare options"},
            {"wait": 6.0},
            {"scroll_to": 320, "over": 5.0},
            {"wait": 3.0},
        ],
    },
    {
        "id": "07-copilot",
        "route": "/app/copilot",
        "narration": (
            "The copilot is deliberately constrained. It receives tool output only, never raw collections. "
            "Every claim it makes carries evidence identifiers that resolve to a real feature or state field. "
            "It holds no write tools, so it can explain an action but it cannot create or approve one. "
            "And with no API key configured at all, it falls back to deterministic templates over the very "
            "same evidence — which is exactly what you are seeing here."
        ),
        "steps": [{"wait": 1.5}, {"click_text": "Ask"}, {"wait": 8.0}, {"scroll_to": 180, "over": 4.0}],
    },
    {
        "id": "08-analytics",
        "route": "/app/admin/analytics",
        "narration": (
            "Then there is the admin console. Full analytics over the same collections the agents read — there is no separate reporting store, so what you see is exactly what the brain saw. Payment volume. Success and failure rate. Breakdowns by method and channel. The order to settlement funnel. And outcome calibration, plotting what was predicted against what was measured. Days with no traffic break the line rather than plotting as zero, because no data is not the same as zero."
        ),
        "steps": [
            {"wait": 5.0},
            {"scroll_to": 420, "over": 5.0},
            {"wait": 3.0},
            {"scroll_to": 980, "over": 5.0},
            {"wait": 3.0},
        ],
    },
    {
        "id": "09-agents",
        "route": "/app/admin/agents",
        "narration": (
            "Trust is earned per agent, per merchant, and it moves only on verified outcomes. Every bid is "
            "persisted, winner or not. "
            "And the decision pipeline shows the whole chain as stored documents — recommendation, policy gate, "
            "approval token, execution, verification, outcome."
        ),
        "steps": [{"wait": 3.5}, {"scroll_to": 340, "over": 5.0}, {"wait": 2.0}],
    },
    {
        "id": "10-testlab",
        "route": "/app/admin/testing",
        "narration": (
            "Finally — everything here is testable from the interface itself. Twenty-one checks across every layer: storage, ingestion, features, world state, anomaly, causal, prediction, simulation, agents and the safety kernel. These are not mocks. Each asserts an invariant against live data — that forecast bands are ordered, that unresolved money reconciles, that the kernel rejects a cross-merchant call. Twenty-one of twenty-one, in about a second. This suite already caught three real bugs in development."
        ),
        "steps": [
            {"wait": 2.0},
            {"click_text": "Include write checks"},
            {"wait": 0.6},
            {"click_text": "Run self-test"},
            {"wait": 7.0},
            {"scroll_to": 300, "over": 5.0},
            {"wait": 4.0},
        ],
    },
    {
        "id": "11-close",
        "route": "/app/admin/system",
        "narration": (
            "Every collection is browsable. Every action is audited. And the whole thing runs with no API keys "
            "at all. "
            "That is Business Brain — not a dashboard that shows a merchant their data, but a system that holds "
            "a view of their business, acts on it carefully, and shows its work every single time."
        ),
        "steps": [{"wait": 3.5}, {"scroll_to": 300, "over": 5.0}, {"wait": 2.5}],
    },
]
