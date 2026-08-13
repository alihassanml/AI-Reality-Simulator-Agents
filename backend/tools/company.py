"""Company-wide tools for the CEO and Investor agents (§9)."""
from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from backend.db import execute, get_company_state, query, query_one, refresh_counters
from backend.deps import AgentDeps


async def get_company_metrics(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """Read the company's current operating metrics: revenue, customers, issues, satisfaction, reputation."""
    await ctx.deps.trace("get_company_metrics", "Reading company metrics")
    state = get_company_state()
    state.pop("id", None)
    return state


async def assign_task(
    ctx: RunContext[AgentDeps], assigned_to: str, description: str, priority: str
) -> dict[str, Any]:
    """Assign a task to an agent. assigned_to is one of: ceo, sales, developer, customer, investor."""
    await ctx.deps.trace("assign_task", f"Assigning to {assigned_to}: {description}")
    task_id = execute(
        """INSERT INTO tasks (assigned_to, description, priority, status, created_at)
           VALUES (?,?,?, 'pending', datetime('now'))""",
        (assigned_to.lower(), description, priority),
    )
    refresh_counters()
    return {"task_id": task_id, "assigned_to": assigned_to, "priority": priority, "status": "pending"}


async def approve_action(ctx: RunContext[AgentDeps], action: str, rationale: str) -> dict[str, Any]:
    """Formally approve a proposed action so the team can execute it."""
    await ctx.deps.trace("approve_action", f"Approving: {action}")
    return {"approved": True, "action": action, "rationale": rationale}


async def get_revenue(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """Read annual revenue and the revenue concentrated in the largest accounts."""
    await ctx.deps.trace("get_revenue", "Pulling revenue figures")
    state = get_company_state()
    customers = query("SELECT name, annual_value FROM customers ORDER BY annual_value DESC")
    top_value = sum(c["annual_value"] for c in customers[:3])
    return {
        "annual_revenue": state["revenue"],
        "top_accounts": customers[:3],
        "top_account_share_pct": round(100 * top_value / state["revenue"], 1) if state["revenue"] else 0,
    }


async def get_customer_metrics(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """Read customer counts, average satisfaction, and which accounts are at risk."""
    await ctx.deps.trace("get_customer_metrics", "Analysing customer base")
    state = get_company_state()
    customers = query("SELECT id, name, tier, annual_value, satisfaction, contract_renewal_days FROM customers")
    at_risk = [c for c in customers if c["satisfaction"] < 70 or c["contract_renewal_days"] < 60]
    avg = round(sum(c["satisfaction"] for c in customers) / len(customers), 1) if customers else 0
    return {
        "total_customers": state["customer_count"],
        "average_satisfaction": avg,
        "at_risk_accounts": at_risk,
    }


async def get_company_report(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """Read a combined report: metrics, open tickets, filed bugs, and pending tasks."""
    await ctx.deps.trace("get_company_report", "Compiling company report")
    state = get_company_state()
    state.pop("id", None)
    return {
        "metrics": state,
        "open_tickets": query("SELECT customer_id, title, priority FROM tickets WHERE status = 'open'"),
        "recent_bugs": query("SELECT title, severity, proposed_fix FROM bug_reports ORDER BY id DESC LIMIT 3"),
        "pending_tasks": query("SELECT assigned_to, description, priority FROM tasks WHERE status = 'pending'"),
    }


async def get_open_tickets(ctx: RunContext[AgentDeps]) -> list[dict[str, Any]]:
    """List the support tickets that are still open, with their ids."""
    await ctx.deps.trace("get_open_tickets", "Listing open tickets")
    return query("SELECT id, customer_id, title, priority FROM tickets WHERE status = 'open' ORDER BY id")


async def resolve_ticket(ctx: RunContext[AgentDeps], ticket_id: int, resolution: str) -> dict[str, Any]:
    """Close an open support ticket once the underlying problem is genuinely fixed."""
    await ctx.deps.trace("resolve_ticket", f"Closing ticket #{ticket_id}")
    row = query_one("SELECT id, status FROM tickets WHERE id = ?", (ticket_id,))
    if row is None:
        return {"error": f"No ticket with id {ticket_id}."}
    if row["status"] != "open":
        return {"error": f"Ticket {ticket_id} is already {row['status']}."}
    execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
    refresh_counters()
    return {"ticket_id": ticket_id, "status": "resolved", "resolution": resolution}


async def complete_task(ctx: RunContext[AgentDeps], task_id: int) -> dict[str, Any]:
    """Mark an assigned task as done."""
    await ctx.deps.trace("complete_task", f"Completing task #{task_id}")
    row = query_one("SELECT id, status FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        return {"error": f"No task with id {task_id}."}
    execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
    refresh_counters()
    return {"task_id": task_id, "status": "done"}
