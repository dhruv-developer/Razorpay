# Business Brain — 5 minute demo script

Numbers below are the live values in your seeded database. Run the pre-flight
once, then don't run another brain cycle before recording or they will drift.

---

## Pre-flight (10 minutes before you record)

```bash
cd /Users/dhruvdawar11/Desktop/Projects/Razorpay-Build-Hackathon
```

1. **Services up.** Mongo, Redis, API, web.

```bash
.venv/bin/python -c "
import socket
for n,p in [('mongo',27017),('redis',6379),('api',8000),('web',3000)]:
    s=socket.socket(); s.settimeout(0.5)
    print(f'{n:6} ' + ('UP' if s.connect_ex(('127.0.0.1',p))==0 else 'DOWN')); s.close()"
```

2. **Browser window at 1440×900 or wider.** The layout switches to a mobile
   strip below 900px. Record in a normal Chrome window, not a narrow one.

3. **Sign in** at http://localhost:3000 — `merchant@atlas.local` /
   `atlas-demo-change-me`. Tick "remember" nothing; just stay signed in.

4. **Dark mode on** (toggle bottom-left of the sidebar). It reads better on video.

5. **Hide clutter** — full-screen the browser, hide the bookmarks bar
   (`⌘⇧B`), close other tabs, turn on Do Not Disturb.

6. **Pre-open these tabs in this order** so you never fumble a URL on camera:

   1. `/app`
   2. `/app/money`
   3. `/app/attention`
   4. `/app/decisions`
   5. `/app/simulate`
   6. `/app/admin/analytics`
   7. `/app/admin/agents`
   8. `/app/admin/testing`

   Switch with `⌃Tab` / `⌘1..⌘8`.

7. **Leave the pending approval alone.** There is exactly 1 action awaiting
   approval — you approve it live at 3:05. Don't click it beforehand.

---

## The script

Total 5:00. ~720 words at a relaxed 145 wpm. Timings are cues, not handcuffs.

---

### 0:00 – 0:30 · Hook (Tab 1 — Overview)

> A merchant on Razorpay opens ten dashboards to answer one question: *am I
> okay?* Payments in one place, settlements in another, payouts in a third.
> Nobody joins them up.
>
> This is Business Brain. One world model per merchant. Events go in — payments,
> settlements, payouts, disputes — and a single state vector comes out that every
> agent reads from.
>
> Here's Atlas Electronics, live.

**Do:** Sit on the Overview page. Don't scroll yet.

---

### 0:30 – 1:15 · The world model (Tab 1 — Overview)

> Revenue in the last 24 hours, thirteen lakh thirteen — down six percent against
> its own seven-day baseline. Cash on hand twenty-five lakh, projected to
> twenty-seven ninety-two in a day, against a reserve floor of twenty lakh the
> merchant set themselves.
>
> But look at the label: **critical**. Not because cash is short — cash is fine.
> Because payment success dropped to eighty-five percent. The 24-hour failure
> rate is fourteen-point-six percent against a seven-day baseline of five-point-nine.
> It's two and a half times normal, and the system noticed before the merchant did.
>
> Every one of these is computed, not stored. Scroll down and you get the cash
> forecast with a p10-to-p90 band, three days of financial weather, and the full
> state vector the agents read before they propose anything.

**Do:** Scroll slowly to the Cash forecast and Financial weather, then the State
vector. Hover one point on the forecast band so the tooltip appears.

---

### 1:15 – 1:50 · Unresolved money (Tab 2)

> Second question every merchant has: where actually *is* my money?
>
> Thirty-six lakh has left a customer but isn't usable cash yet. The system
> splits it by how recoverable it is — twenty lakh recoverable inside 48 hours.
> Pending settlements, twenty-one lakh, ninety percent of that lands on the
> normal cycle. Failed payments, two-point-six lakh, thirty percent retryable.
> Scheduled payouts, twelve lakh — that's committed, it's leaving.
>
> These aren't guesses. The recovery rate on each bucket is this merchant's own
> historical rate, and every chart has a table view so no number is trapped
> behind a hover.

**Do:** Land on the page. Click **Table** on the "Unresolved money by bucket"
card for two seconds, then click back to **Chart**.

---

### 1:50 – 2:30 · Attention + causality (Tab 3)

> So what do I do about it? The attention queue ranks by impact times urgency
> times confidence times reversibility — a real score, not a rules list.
>
> Two items. Settlements delayed, ten-point-four lakh. And payment failures
> rising, marked high, with the reasoning attached: fourteen-point-six percent
> against a five-point-nine baseline.
>
> And every item carries its evidence IDs — the exact feature and state fields
> it was derived from. Scroll down and there's the causal graph: domain edges
> whose strength is measured from this merchant's own time series, not assumed.
> Failure rate against success rate: minus one. Measured, not hardcoded.

**Do:** Scroll to the causal graph. Point at the `failure_rate → success_rate`
row showing **−1.000**.

---

### 2:30 – 3:20 · The decision + live approval (Tab 4)

> Now the part that matters. Four specialist agents bid on this. The orchestrator
> scored them under the merchant's own objective weights and picked one:
> retry the failed payments, thirteen-point-four lakh.
>
> But here's what I care about — it shows you what it *rejected*. "Do nothing"
> was considered and dropped, because doing nothing leaves reserve-breach
> probability at eight-point-six percent.
>
> On the right: the evidence it rests on, copied from world state at decision
> time, and the expected impact — simulated before anything executes.
>
> And it cannot act on its own. This is a financial action, so policy holds it.
> Let me approve it.

**Do:** Click the **Approvals** tab → click **Approve** on the pending row.
Wait for the counters to move, then say:

> Approved, executed, verified — and the measured impact went into the outcome
> ledger. Not the estimate. What actually happened.

---

### 3:20 – 3:50 · What-if (Tab 5)

> Before you commit, you can ask what-if. Same simulation engine the orchestrator
> uses to score its own options.

**Do:** Click **Compare options**. Wait for the six rows.

> Six scenarios against the same starting state. Do nothing: twenty-seven ninety-two.
> Delay payouts twelve hours: plus three lakh. Everything at once: plus six and a
> half lakh, and reserve-breach risk drops from eight-point-six to seven percent.
> Nothing here touches money — it only scores.

---

### 3:50 – 4:25 · Admin: analytics and trust (Tabs 6 → 7)

> Everything the brain sees, the admin sees.

**Do:** Tab 6. Scroll through the charts as you talk.

> Thirty days: two-point-nine-eight crore captured, ninety-five-point-seven percent
> success. UPI is the volume leader at one-point-four-six crore and also the worst
> failure rate. The full order-to-settlement funnel. Outcome calibration — predicted
> impact against measured impact, so you can see where the agents are wrong.

**Do:** Switch to Tab 7.

> And trust is earned, per merchant. Four agents, each declaring its own
> capabilities. Trust only moves on a verified outcome, and every bid is logged
> whether it won or lost. Circuit breakers cap how often any agent can act.

---

### 4:25 – 4:50 · Test lab, live (Tab 8)

> Last thing — and this is the part I'd want to see if I were judging.

**Do:** Tick **Include write checks**, click **Run self-test**. Wait ~1.5s.

> Twenty-one checks, end to end, against live data. Not mocks. It asserts that
> forecast bands are ordered, that unresolved money reconciles to its buckets,
> that the safety kernel rejects cross-merchant calls, that replaying an event ID
> is deduplicated, and that an action's full lifecycle lands in the outcome ledger
> exactly once.
>
> All twenty-one green, in about a second. This suite found two real bugs during
> development — a double-counted outcome on replay, and an inverted sign in the
> causal graph.

---

### 4:50 – 5:00 · Close

> One world model. Agents that bid and explain what they rejected. A safety kernel
> that won't let them move money unattended. And every layer visible and testable
> from the console.
>
> That's Business Brain. Thanks for watching.

---

## Numbers cheat-sheet (spoken form)

| On screen | Say |
|---|---|
| ₹13.13L | thirteen lakh thirteen |
| ₹25.00L / ₹27.92L / ₹20.00L | twenty-five lakh / twenty-seven ninety-two / twenty lakh |
| 14.6% vs 5.9% | fourteen-point-six against five-point-nine |
| ₹36.36L / ₹20.08L | thirty-six lakh / twenty lakh recoverable |
| ₹2.98Cr | two-point-nine-eight crore |
| ₹13.39L | thirteen-point-four lakh |
| 21/21 | twenty-one of twenty-one |

## If something goes wrong on camera

- **A page looks empty** — hit Refresh in the page header, keep talking.
- **The approval is already gone** — go to Test lab → Action probe, create a
  `refund.create` for `9000000`, and approve/reject that instead. Same pipeline.
- **Numbers differ from this script** — read what's on screen. Don't read the
  script number. The story works with any values.
