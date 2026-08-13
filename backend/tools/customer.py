"""Customer-facing tools, used mainly by the Sales agent (§9)."""
from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from backend.db import execute, query, query_one, refresh_counters
from backend.deps import AgentDeps


async def get_customer(ctx: RunContext[AgentDeps], customer_id: str) -> dict[str, Any]:
    """Look up a customer's account record: tier, annual value, satisfaction, renewal date."""
    await ctx.deps.trace("get_customer", f"Looking up account '{customer_id}'")
    row = query_one("SELECT * FROM customers WHERE id = ?", (customer_id.lower(),))
    return row or {"error": f"No customer with id '{customer_id}'."}


async def get_customer_history(ctx: RunContext[AgentDeps], customer_id: str) -> list[dict[str, Any]]:
    """Retrieve the dated history of incidents, escalations and expansions for a customer."""
    await ctx.deps.trace("get_customer_history", f"Reading support history for '{customer_id}'")
    return query(
        "SELECT occurred_at, kind, summary FROM customer_history WHERE customer_id = ? ORDER BY occurred_at",
        (customer_id.lower(),),
    )


async def create_ticket(
    ctx: RunContext[AgentDeps], customer_id: str, title: str, priority: str
) -> dict[str, Any]:
    """Open a support ticket for a customer. Priority is one of: low, normal, high, critical."""
    await ctx.deps.trace("create_ticket", f"Opening {priority} ticket: {title}")
    ticket_id = execute(
        """INSERT INTO tickets (customer_id, title, priority, status, created_at)
           VALUES (?,?,?, 'open', datetime('now'))""",
        (customer_id.lower(), title, priority),
    )
    refresh_counters()
    return {"ticket_id": ticket_id, "status": "open", "title": title, "priority": priority}
