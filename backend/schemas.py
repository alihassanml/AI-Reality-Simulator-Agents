"""Structured shapes exchanged between agents, engine, and UI.

Every agent returns an AgentDecision. The engine turns it into timeline events
and state deltas; the frontend renders it as a decision card (§12).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AgentName = Literal["ceo", "sales", "developer", "customer", "investor"]
Priority = Literal["low", "normal", "high", "critical"]

AGENT_LABELS: dict[str, str] = {
    "ceo": "CEO Agent",
    "sales": "Sales Agent",
    "developer": "Developer Agent",
    "customer": "Customer Agent",
    "investor": "Investor Agent",
}


class AgentMessage(BaseModel):
    """A structured message from one agent to another (§7)."""

    to: AgentName = Field(description="Which agent receives this message.")
    subject: str = Field(description="One-line subject, under 80 characters.")
    body: str = Field(description="The message body. Be specific and cite facts you retrieved with tools.")
    priority: Priority = Field(description="How urgent this is for the recipient.")


class StateDelta(BaseModel):
    """Signed changes this decision makes to how the company is regarded (§13).

    Only judgements live here, on a 0-100 scale. Counts of issues and tasks are
    facts, derived from the ticket and task tables, so no agent can assert them.
    """

    satisfaction: int = Field(default=0, ge=-30, le=30, description="Change to customer satisfaction.")
    reputation: int = Field(default=0, ge=-30, le=30, description="Change to company reputation.")
    investor_confidence: int = Field(default=0, ge=-30, le=30, description="Change to investor confidence.")

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in self.model_dump().items() if v}

    def is_empty(self) -> bool:
        return not self.as_dict()


class AgentDecision(BaseModel):
    """What an agent concluded on its turn."""

    thought: str = Field(
        description="One short sentence, first person, describing what you are doing right now. "
                    "This is shown live on the dashboard, e.g. 'Reviewing ACME's support history'."
    )
    decision: str = Field(
        max_length=48,
        description="A short lowercase snake_case slug naming the action, at most four words, "
                    "e.g. escalate_to_ceo or approve_timeout_fix. Not a sentence.",
    )
    reason: str = Field(description="Why you decided this, in one or two sentences, grounded in facts you retrieved.")
    priority: Priority = Field(description="How urgent your decision is.")
    assigned_to: AgentName | None = Field(
        default=None, description="The agent responsible for the next action, if you are assigning one."
    )
    message: AgentMessage | None = Field(
        default=None, description="A message to send to another agent. Omit if no one needs to be told."
    )
    state_delta: StateDelta = Field(
        default_factory=StateDelta, description="How this changes the company's numbers. Use zeros if nothing changes."
    )
    remember: str | None = Field(
        default=None,
        description="A durable fact worth storing in your long-term memory for future events. Omit if nothing new.",
    )

    @field_validator("decision", mode="before")
    @classmethod
    def _slugify(cls, value: object) -> str:
        """Models occasionally answer with a sentence. Force it back to a label.

        The decision slug is rendered as a heading on the dashboard, so an
        unbounded string would break the card layout.
        """
        text = str(value).strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        if len(slug) > 48:
            slug = "_".join(slug.split("_")[:4])[:48].strip("_")
        return slug or "acted"
