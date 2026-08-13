"""Engineering tools, used by the Developer agent (§9)."""
from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from backend.db import execute, query, query_one
from backend.deps import AgentDeps


def _resolve_service(name: str) -> str | None:
    """Match a service the way an agent is likely to type it.

    Models freely swap hyphens and underscores, so 'payment_api' has to find
    'payment-api' rather than returning nothing and burning a turn.
    """
    if not name:
        return None
    needle = name.strip().lower().replace("_", "-")
    exact = query_one("SELECT name FROM services WHERE lower(name) = ?", (needle,))
    if exact:
        return exact["name"]
    stem = needle.split("-")[0].rstrip("s")
    fuzzy = query_one("SELECT name FROM services WHERE lower(name) LIKE ?", (f"%{stem}%",))
    return fuzzy["name"] if fuzzy else None


async def get_logs(ctx: RunContext[AgentDeps], service: str = "", limit: int = 12) -> list[dict[str, Any]]:
    """Read recent application logs. Pass a service name to filter, or leave blank for all services."""
    resolved = _resolve_service(service)
    await ctx.deps.trace("get_logs", f"Pulling logs for {resolved or 'all services'}")
    if resolved:
        return query(
            "SELECT logged_at, service, level, message FROM logs WHERE service = ? ORDER BY logged_at DESC LIMIT ?",
            (resolved, limit),
        )
    return query(
        "SELECT logged_at, service, level, message FROM logs ORDER BY logged_at DESC LIMIT ?", (limit,)
    )


async def search_errors(ctx: RunContext[AgentDeps], keyword: str) -> list[dict[str, Any]]:
    """Search ERROR and WARN log lines for a keyword, e.g. 'timeout' or 'payment'."""
    await ctx.deps.trace("search_errors", f"Searching error logs for '{keyword}'")
    return query(
        """SELECT logged_at, service, level, message FROM logs
           WHERE level IN ('ERROR','WARN') AND message LIKE ?
           ORDER BY logged_at DESC LIMIT 12""",
        (f"%{keyword}%",),
    )


async def check_service_status(ctx: RunContext[AgentDeps], service: str = "") -> Any:
    """Check health, latency and error rate for one service, or all of them if left blank."""
    resolved = _resolve_service(service)
    await ctx.deps.trace("check_service_status", f"Checking status of {resolved or 'all services'}")
    if service:
        if not resolved:
            known = [r["name"] for r in query("SELECT name FROM services")]
            return {"error": f"No service named '{service}'.", "known_services": known}
        return query_one("SELECT * FROM services WHERE name = ?", (resolved,))
    return query("SELECT * FROM services ORDER BY status DESC, latency_ms DESC")


async def create_bug_report(
    ctx: RunContext[AgentDeps], title: str, root_cause: str, severity: str, proposed_fix: str
) -> dict[str, Any]:
    """File a bug report with the root cause you identified and the fix you recommend."""
    await ctx.deps.trace("create_bug_report", f"Filing bug report: {title}")
    bug_id = execute(
        """INSERT INTO bug_reports (title, root_cause, severity, proposed_fix, created_at)
           VALUES (?,?,?,?, datetime('now'))""",
        (title, root_cause, severity, proposed_fix),
    )
    return {"bug_id": bug_id, "title": title, "severity": severity, "proposed_fix": proposed_fix}
