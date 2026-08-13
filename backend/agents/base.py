"""Agent construction shared by all five characters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent

from backend.config import MODEL_NAME
from backend.deps import AgentDeps
from backend.schemas import AgentDecision

HOUSE_RULES = """
You are a character inside a simulated software company. You are not a chatbot and
you never speak to a user -- you act, and you talk to your colleagues.

How you must behave:
- Use your tools to get facts before you decide. Never invent a number, a log line,
  or a customer detail that a tool could have told you.
- Stay in character. Your personality shapes your tone and what you prioritise.
- Keep every field short. `thought` is one sentence in the present tense describing
  what you are doing right now, because it is displayed live on a dashboard.
- Only set `message` when a specific colleague genuinely needs to hear from you.
- `state_delta` is how your action moves the company's numbers. Most actions move
  nothing; leave zeros unless your action clearly helps or hurts.
- Only the customer changes `satisfaction`, and only the investor changes
  `investor_confidence`. If you are neither, leave those at zero.
- The counts of open issues and pending tasks are not yours to state. They follow
  from the tickets and tasks themselves, so close a ticket or complete a task with
  the matching tool when the work is genuinely done.
- Set `remember` only for a fact that will still matter during a future, unrelated event.
""".strip()


@dataclass
class AgentProfile:
    """A character: who they are, and the Pydantic AI agent that thinks for them."""

    name: str
    label: str
    role: str
    personality: str
    goals: list[str]
    agent: Agent[AgentDeps, AgentDecision]
    tool_names: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "role": self.role,
            "personality": self.personality,
            "goals": self.goals,
            "tools": self.tool_names,
        }


def build_agent(
    *,
    name: str,
    label: str,
    role: str,
    personality: str,
    goals: list[str],
    instructions: str,
    tools: list[Any],
) -> AgentProfile:
    """Assemble one character into a runnable agent."""
    goal_lines = "\n".join(f"- {g}" for g in goals)
    full_instructions = (
        f"{HOUSE_RULES}\n\n"
        f"# Who you are\n"
        f"You are the {label} of the company.\n\n"
        f"Role: {role}\n\n"
        f"Personality: {personality}\n\n"
        f"Your standing goals:\n{goal_lines}\n\n"
        f"# How you work\n{instructions.strip()}"
    )
    agent = Agent(
        MODEL_NAME,
        output_type=AgentDecision,
        deps_type=AgentDeps,
        instructions=full_instructions,
        tools=tools,
        retries=2,
        name=name,
    )
    return AgentProfile(
        name=name,
        label=label,
        role=role,
        personality=personality,
        goals=goals,
        agent=agent,
        tool_names=[t.__name__ for t in tools],
    )
