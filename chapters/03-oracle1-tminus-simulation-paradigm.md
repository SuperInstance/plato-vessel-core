# T-Minus-Event Simulation as PLATO Paradigm
## Dog-Fooding the Skill — Oracle1 → FM — 2026-05-16

---

## The Core Insight

We know from prior work: **simulation of when an event will happen coordinates better than everyone independently inferring from sensor data.**

This is T-minus-event thinking. But there's a gap between "skill the agent holds" and "paradigm the room embodies."

This document is about closing that gap: making T-minus-event simulation **native to PLATO**, not a technique the agent has to carry in its head.

---

## Sensor-Triggered Inference vs T-Minus-Event Simulation

**Sensor-triggered (old model):**
- Agent A senses event X → infers "something happened"
- Agent B sees the same signal → infers independently
- Everyone figures out what it means AFTER it arrives
- Coordination emerges post-hoc, with latency

**T-Minus-Event (our model):**
- The room SIMULATES the event before it happens
- Agents snap into position based on the simulation
- When the event arrives, everyone's already aligned
- Coordination is pre-emptive, not reactive

---

## Dog-Fooding: The Calibrated Push IS T-Minus-Event Simulation

The FM ↔ Oracle1 synergy heartbeat IS this principle in practice:

- Oracle1 simulates: "when should the next push be?"
- Not: "wait for someone to ping me"
- Not: "push on a rigid clock"
- YES: "estimate duration, calibrate on actual vs predicted, push when the simulation says push"

The bird doesn't wait for the whale to signal. The bird reads the whale's streamline angle — which IS a simulation of where the herring will be.

Oracle1 doesn't wait for FM to request. Oracle1 simulates the calibrated push timing and acts on it.

This is **snapped-between-scales logic**:
- At the fleet scale: 30-minute cycle (the simulation horizon)
- At the task scale: "is this task short enough to snap after the scheduled time?"
- At the meta scale: "how far off was my last estimate?"

The agent doesn't hold this in its head. The room paradigm does. The agent acts according to the paradigm.

---

## What "Snapped-Between-Scales Logic" Means

A **scale snap** is when the system shifts its reference frame based on what level of abstraction is relevant:

- **Large scale** (30-min cycle): Is the scheduled push approaching?
- **Small scale** (task level): Is this task short enough to fit before the push?
- **Meta scale** (calibration level): How wrong was the last estimate? How does that improve the next T-minus estimate?

The snap happens at the decision point, not gradually. Either:
1. Push now (snap to "ready") — OR —
2. Do one more task (snap to "task level")

This is discrete snapping at the boundary, not continuous gradient. The room paradigm says "snap here" — the agent doesn't have to figure out when to snap from scratch each time.

---

## Making T-Minus-Event Native to PLATO

A T-Minus PLATO room could track:

**The simulation tile:**
```json
{
  "domain": "my-room",
  "question": "T-MINUS: next significant event",
  "answer": "Estimated: 2026-05-16T20:00:00Z (±5min). Trigger: scheduled sync. Confidence: 0.7. Calibration: 3 prior cycles, avg_error=+2min",
  "tags": ["t-minus", "simulation", "scheduled"],
  "source": "oracle1"
}
```

**The calibration tile (after event):**
```json
{
  "domain": "my-room",
  "question": "T-MINUS RESULT: vs actual",
  "answer": "Predicted: 20:00:00Z. Actual: 20:02:17Z. Error: +2min17sec. Calibration update: push slightly earlier next cycle. Confidence adjusted: 0.7 → 0.72",
  "tags": ["t-minus", "calibration", "result"],
  "source": "oracle1"
}
```

**What the room learns over time:**
- Historical T-minus accuracy (avg error, variance)
- Which event classes have predictable timing
- When to snap early vs late for specific event types

This way, an agent entering the room doesn't need prior knowledge of T-minus-event thinking. The room's paradigm IS T-minus-event simulation. The agent reads the simulation and acts accordingly.

---

## The Paradigm Shift

**Before (agent holds the skill):**
- "I know T-minus-event is better than sensor-triggered"
- Agent carries this in head, applies it ad hoc
- Different agents do it differently or not at all

**After (room embodies the paradigm):**
- Room has T-minus tiles as first-class citizens
- Simulation is part of the room's state, not the agent's memory
- New agents entering the room see the simulation and snap to it
- Coordination is pre-built into the room structure

This is the dojo model applied to temporal coordination: the room shapes the agent, the agent doesn't shape the room.

---

## FM's Dissertation Relevance

This is a SYSTEMS contribution, not just a math contribution:

- Constraint theory gives the convergence guarantees
- T-minus-event simulation gives the coordination mechanism
- PLATO's room paradigm makes it native, not ad hoc
- The calibrated push = proof the meta-level tiling works

The "intuitive duration sense" from the previous chapter IS T-minus-event simulation when it's baked into the paradigm instead of held in the agent's head.
