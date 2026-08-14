"""The simulation engine: runs an event's workflow through the agents (§6).

One run at a time. Each step gives an agent its task plus its memory, lets it call
tools, and turns the structured decision it returns into visible dashboard events
and changes to company state.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from typing import Any

from backend.agents import ORDER, get as get_agent
from backend.config import MIN_STEP_SECONDS
from backend.db import apply_state_delta, dump_json, execute, get_company_state, refresh_counters
from backend.deps import AgentDeps
from backend.memory import long_term
from backend.memory.short_term import ShortTermMemory
from backend.schemas import AGENT_LABELS, AgentDecision
from backend.simulation import events as event_defs
from backend.simulation.bus import bus

IDLE, RUNNING, PAUSED, COMPLETED, FAILED = "idle", "running", "paused", "completed", "failed"

# Some numbers belong to one character and nobody else. A sales agent cannot
# decide how satisfied the customer feels, and only the investor sets investor
# confidence. Enforced here rather than left to the prompt, because a model that
# drifts here corrupts the whole company state.
DELTA_OWNERS: dict[str, set[str]] = {
    "satisfaction": {"customer"},
    "investor_confidence": {"investor"},
    "reputation": {"ceo", "investor", "customer"},
}


def _authorised_deltas(actor: str, deltas: dict[str, int]) -> tuple[dict[str, int], list[str]]:
    """Split a decision's deltas into the ones this actor may apply and the rest."""
    allowed, refused = {}, []
    for field, value in deltas.items():
        owners = DELTA_OWNERS.get(field)
        if owners and actor not in owners:
            refused.append(field)
        else:
            allowed[field] = value
    return allowed, refused


class SimulationEngine:
    def __init__(self) -> None:
        self.status: str = IDLE
        self.run_id: str | None = None
        self.event_key: str | None = None
        self.definition: event_defs.EventDefinition | None = None
        self.current_step: int = 0
        self.total_steps: int = 0
        self.current_actor: str | None = None
        self.stm = ShortTermMemory()
        self.agent_status: dict[str, dict[str, str]] = {}
        self._resume = asyncio.Event()
        self._resume.set()
        self._task: asyncio.Task | None = None
        self._reset_agent_status()

    # ---------------------------------------------------------------- state

    def _reset_agent_status(self) -> None:
        self.agent_status = {
            name: {"status": "idle", "detail": "Waiting"} for name in ORDER
        }

    def snapshot(self) -> dict[str, Any]:
        """Everything the dashboard needs to draw itself from scratch."""
        return {
            "status": self.status,
            "run_id": self.run_id,
            "event": self.definition.as_dict() if self.definition else None,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "current_actor": self.current_actor,
            "agents": self.agent_status,
            "company": get_company_state(),
        }

    async def _push_status(self) -> None:
        await bus.emit("simulation_status", self.snapshot())

    async def _set_agent(self, agent: str, status: str, detail: str) -> None:
        self.agent_status[agent] = {"status": status, "detail": detail}
        await bus.emit("agent_status", {"agent": agent, "status": status, "detail": detail})

    # ------------------------------------------------------------- controls

    def is_busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def trigger(self, event_key: str, prompt: str = "") -> dict[str, Any]:
        """Start a preset scenario, or a situation the user described themselves."""
        if self.is_busy():
            return {"ok": False, "error": "A simulation is already running."}
        if event_key == "custom":
            definition = event_defs.build_custom_event(prompt)
        else:
            definition = event_defs.get(event_key)
        self._task = asyncio.create_task(self._run(definition))
        return {"ok": True, "event": definition.as_dict()}

    async def pause(self) -> dict[str, Any]:
        if self.status != RUNNING:
            return {"ok": False, "error": "Nothing is running."}
        self._resume.clear()
        self.status = PAUSED
        await self._push_status()
        return {"ok": True}

    async def resume(self) -> dict[str, Any]:
        if self.status != PAUSED:
            return {"ok": False, "error": "The simulation is not paused."}
        self._resume.set()
        self.status = RUNNING
        await self._push_status()
        return {"ok": True}

    async def reset(self) -> dict[str, Any]:
        """Stop any run and put the world back to its seeded state."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

        from backend.db import init_db
        init_db(reset=True)

        self.status = IDLE
        self.run_id = None
        self.event_key = None
        self.definition = None
        self.current_step = 0
        self.total_steps = 0
        self.current_actor = None
        self.stm.clear()
        self._reset_agent_status()
        self._resume.set()

        bus.clear()
        await bus.emit("simulation_reset", {})
        await self._push_status()
        return {"ok": True}

    # ------------------------------------------------------------ execution

    async def _run(self, definition: event_defs.EventDefinition) -> None:
        self.run_id = uuid.uuid4().hex[:12]
        self.event_key = definition.key
        self.definition = definition
        self.status = RUNNING
        self.current_step = 0
        self.total_steps = len(definition.steps)
        self.stm.clear()
        self._reset_agent_status()

        execute(
            "INSERT INTO runs (id, event_type, status, started_at) VALUES (?,?,?, datetime('now'))",
            (self.run_id, definition.key, RUNNING),
        )
        await bus.emit("run_started", {
            "run_id": self.run_id,
            "event": definition.as_dict(),
            "company": get_company_state(),
        })
        await self._push_status()

        try:
            for index, step in enumerate(definition.steps, start=1):
                await self._resume.wait()
                self.current_step = index
                self.current_actor = step.actor
                await self._push_status()
                await self._run_step(index, step)

            self.status = COMPLETED
            self.current_actor = None
            for name in ORDER:
                current = self.agent_status[name]
                if current["status"] not in ("done", "idle"):
                    await self._set_agent(name, "done", "Finished")
            execute("UPDATE runs SET status = ?, ended_at = datetime('now') WHERE id = ?",
                    (COMPLETED, self.run_id))
            await bus.emit("run_completed", {
                "run_id": self.run_id,
                "company": get_company_state(),
            })
            await self._push_status()

        except asyncio.CancelledError:
            self.status = IDLE
            raise
        except Exception as exc:  # surface the failure on the dashboard, don't swallow it
            self.status = FAILED
            execute("UPDATE runs SET status = ?, ended_at = datetime('now') WHERE id = ?",
                    (FAILED, self.run_id))
            await bus.emit("run_failed", {"error": f"{type(exc).__name__}: {exc}"})
            await self._push_status()

    async def _run_step(self, index: int, step: event_defs.Step) -> None:
        profile = get_agent(step.actor)
        started = time.monotonic()

        await self._set_agent(step.actor, "thinking", step.label)
        await bus.emit("step_started", {
            "index": index,
            "actor": step.actor,
            "actor_label": AGENT_LABELS[step.actor],
            "label": step.label,
        })

        deps = AgentDeps(agent=step.actor, run_id=self.run_id or "", stm=self.stm, emit=bus.emit)
        prompt = self._compose_prompt(step)

        result = await profile.agent.run(prompt, deps=deps)
        decision: AgentDecision = result.output

        await self._set_agent(step.actor, "working", decision.thought)
        await bus.emit("thought", {"actor": step.actor, "text": decision.thought})

        await self._apply_decision(index, step, decision)

        # Hold the step on screen long enough to be readable.
        elapsed = time.monotonic() - started
        if elapsed < MIN_STEP_SECONDS:
            await asyncio.sleep(MIN_STEP_SECONDS - elapsed)

        await self._set_agent(step.actor, "done", f"✓ {decision.decision.replace('_', ' ')}")

    def _compose_prompt(self, step: event_defs.Step) -> str:
        """Task + memory + world state, assembled into this turn's prompt."""
        company = get_company_state()
        company.pop("id", None)
        metrics = ", ".join(f"{k}={v}" for k, v in company.items())
        return (
            f"# Your task right now\n{step.task}\n\n"
            f"# Your long-term memory\n{long_term.recall_text(step.actor, step.subjects or None)}\n\n"
            f"# Your short-term memory\n{self.stm.recall(step.actor)}\n\n"
            f"# Current company state\n{metrics}\n\n"
            f"Decide and act now."
        )

    async def _apply_decision(self, index: int, step: event_defs.Step, decision: AgentDecision) -> None:
        actor = step.actor

        self._record(index, "decision", actor, None, decision.model_dump())
        await bus.emit("decision", {
            "actor": actor,
            "actor_label": AGENT_LABELS[actor],
            "decision": decision.decision,
            "reason": decision.reason,
            "priority": decision.priority,
            "assigned_to": decision.assigned_to,
            "assigned_to_label": AGENT_LABELS.get(decision.assigned_to or "", None),
        })
        self.stm.note(actor, f"{decision.decision}: {decision.reason}")

        if decision.message:
            msg = decision.message
            line = f"From {AGENT_LABELS[actor]} {msg.subject}: {msg.body}"
            self.stm.deliver(msg.to, line)
            self._record(index, "message", actor, msg.to, msg.model_dump())
            await bus.emit("message", {
                "from": actor,
                "from_label": AGENT_LABELS[actor],
                "to": msg.to,
                "to_label": AGENT_LABELS[msg.to],
                "subject": msg.subject,
                "body": msg.body,
                "priority": msg.priority,
            })

        for notified in step.notify:
            self.stm.deliver(notified, f"{AGENT_LABELS[actor]} decided: {decision.decision} {decision.reason}")

        if not decision.state_delta.is_empty():
            deltas, refused = _authorised_deltas(actor, decision.state_delta.as_dict())
            if refused:
                self._record(index, "delta_refused", actor, None, {"fields": refused})
            if deltas:
                company = apply_state_delta(**deltas)
                self._record(index, "state", actor, None, {"delta": deltas, "state": company})
                await bus.emit("state_update", {"delta": deltas, "company": company, "actor": actor})

        # Tickets and tasks may have moved during this turn; the counters follow.
        before = get_company_state()
        after = refresh_counters()
        counter_delta = {
            field: after[field] - before[field]
            for field in ("active_issues", "pending_tasks")
            if after[field] != before[field]
        }
        if counter_delta:
            await bus.emit("state_update", {"delta": counter_delta, "company": after, "actor": actor})

        if decision.remember:
            subject = step.subjects[0] if step.subjects else "general"
            long_term.remember(actor, subject, decision.remember, importance=3)
            await bus.emit("memory_stored", {"agent": actor, "content": decision.remember})

    def _record(self, seq: int, kind: str, actor: str | None, target: str | None, payload: dict) -> None:
        if not self.run_id:
            return
        execute(
            """INSERT INTO run_events (run_id, seq, at, kind, actor, target, payload)
               VALUES (?,?,?,?,?,?,?)""",
            (self.run_id, seq, datetime.now().isoformat(timespec="seconds"), kind, actor, target,
             dump_json(payload)),
        )


engine = SimulationEngine()
