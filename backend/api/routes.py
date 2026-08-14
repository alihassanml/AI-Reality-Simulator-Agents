"""REST controls for the simulation (§18)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.agents import roster
from backend.db import get_company_state, query
from backend.memory import long_term
from backend.simulation import events as event_defs
from backend.simulation.bus import bus
from backend.simulation.engine import engine

router = APIRouter(prefix="/api")


class TriggerRequest(BaseModel):
    event: str = "customer_complaint"
    prompt: str = ""


class ContactRequest(BaseModel):
    """One submission of the public contact form."""

    name: str = ""
    email: str = ""
    message: str = ""


@router.get("/state")
async def read_state() -> dict:
    """Everything needed to draw the dashboard on first load."""
    return {
        "simulation": engine.snapshot(),
        "agents": roster(),
        "events": event_defs.catalog(),
        "company": get_company_state(),
        "history": bus.history(),
    }


@router.post("/simulation/trigger")
async def trigger(req: TriggerRequest) -> dict:
    try:
        return await engine.trigger(req.event, req.prompt)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc).strip('"')}


@router.post("/contact")
async def contact(req: ContactRequest) -> dict:
    """The public front door: a message from outside starts a run.

    It goes through the same custom-event path as the dashboard's own input,
    so the browsers already listening on /ws light up without being told.
    """
    message = req.message.strip()
    if not message:
        return {"ok": False, "error": "Write a message before sending it."}

    name, email = req.name.strip(), req.email.strip()
    sender = f"{name} <{email}>" if name and email else (name or email)

    try:
        return await engine.trigger("custom", message, sender)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc).strip('"')}


@router.post("/simulation/pause")
async def pause() -> dict:
    return await engine.pause()


@router.post("/simulation/resume")
async def resume() -> dict:
    return await engine.resume()


@router.post("/simulation/reset")
async def reset() -> dict:
    return await engine.reset()


@router.get("/agents/{name}/memory")
async def agent_memory(name: str) -> dict:
    return {
        "agent": name,
        "long_term": long_term.all_for(name),
        "short_term": {
            "inbox": engine.stm.inbox.get(name, []),
            "notes": engine.stm.notes.get(name, []),
        },
    }


@router.get("/company")
async def company() -> dict:
    return {
        "state": get_company_state(),
        "tickets": query("SELECT * FROM tickets ORDER BY id DESC LIMIT 10"),
        "bugs": query("SELECT * FROM bug_reports ORDER BY id DESC LIMIT 10"),
        "tasks": query("SELECT * FROM tasks ORDER BY id DESC LIMIT 10"),
    }
