"""Declarative event workflows (§5, §6).

An event is a list of turns. Each turn names the agent who acts and the task put
in front of them. Adding a new scenario means adding an EventDefinition here --
no engine changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    """One agent turn in a workflow."""

    actor: str
    label: str            # short line shown while this step runs
    task: str             # the prompt handed to the agent
    subjects: list[str] = field(default_factory=list)   # long-term memory to recall
    notify: list[str] = field(default_factory=list)     # agents who also see the result


@dataclass
class EventDefinition:
    key: str
    title: str
    summary: str
    priority: str
    icon: str
    steps: list[Step]

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "summary": self.summary,
            "priority": self.priority,
            "icon": self.icon,
            "step_count": len(self.steps),
        }


CUSTOMER_COMPLAINT = EventDefinition(
    key="customer_complaint",
    title="Customer Complaint",
    summary="ACME Corporation reports that payments are failing in production.",
    priority="critical",
    icon="alert",
    steps=[
        Step(
            actor="customer",
            label="Filing a complaint",
            task=(
                "Payments have been failing for your company for the last half hour. "
                "Checkouts time out and your finance team is blocked. Write the complaint "
                "you are sending to your vendor's sales contact right now. Address your "
                "message to sales, and set state_delta.satisfaction to reflect how this "
                "incident has affected your view of them."
            ),
            subjects=["self"],
        ),
        Step(
            actor="sales",
            label="Reviewing the account",
            task=(
                "A complaint just arrived from ACME Corporation (customer id 'acme'). "
                "Look up the account and its history, open a ticket, and decide how serious "
                "this is for the business. Escalate to the CEO with the account value, the "
                "renewal timing, and a specific recommended action."
            ),
            subjects=["acme"],
        ),
        Step(
            actor="ceo",
            label="Deciding who owns it",
            task=(
                "Sales has escalated a critical customer issue to you. Check the company's "
                "metrics, then assign this to exactly one agent with a clear definition of "
                "done, and message them directly."
            ),
            subjects=["acme", "policy"],
        ),
        Step(
            actor="developer",
            label="Investigating the failure",
            task=(
                "You have been assigned to investigate why payments are failing for ACME. "
                "Check service health, read the logs, and search the errors for the symptom. "
                "Identify the root cause with evidence, file a bug report, and send your "
                "findings and proposed fix to the CEO."
            ),
            subjects=["payment-api"],
        ),
        Step(
            actor="ceo",
            label="Approving the fix",
            task=(
                "Engineering has reported back with a root cause and a proposed fix. "
                "Approve or reject it explicitly, then tell sales what to communicate to "
                "the customer. Be specific about what the customer will be told. "
                "Your approval closes this incident: look up the open tickets, resolve the "
                "ACME one, and complete the task you assigned to the developer."
            ),
            subjects=["acme", "policy"],
        ),
        Step(
            actor="sales",
            label="Communicating the resolution",
            task=(
                "The CEO has decided how to resolve the ACME issue. Write the message you "
                "are sending back to the customer. Explain the root cause plainly, say what "
                "is being done, and address the fact that their renewal is close."
            ),
            subjects=["acme"],
        ),
        Step(
            actor="customer",
            label="Reacting to the response",
            task=(
                "Your vendor has responded to your complaint. React honestly to how they "
                "handled it -- the speed, the specificity, and whether they took it "
                "seriously. Set state_delta.satisfaction to reflect your revised view."
            ),
            subjects=["self"],
        ),
        Step(
            actor="investor",
            label="Assessing business impact",
            task=(
                "A critical incident affecting a top-three account has just been handled. "
                "Pull the revenue and customer numbers, review how it was handled, and record "
                "your judgement of the business impact and of leadership's response."
            ),
            subjects=["revenue"],
        ),
    ],
)

# A generic six-turn flow for a situation the user types in themselves. The
# preset above is hand-written for a complaint; this one has to work for anything
# from a security incident to a tripled cloud bill, so it starts with the CEO
# triaging rather than assuming a customer is involved.
CUSTOM_STEPS = [
    ("ceo", "Triaging the situation",
     "This situation has just landed on your desk:\n\n\"{text}\"\n\n"
     "Check the company's metrics, judge how serious this is, and assign it to "
     "exactly one agent with a clear definition of done."),
    ("developer", "Investigating",
     "You have been asked to look into this situation:\n\n\"{text}\"\n\n"
     "Investigate whatever technical angle exists -- service health, logs, errors. "
     "If it is not a technical problem, say so plainly rather than inventing one. "
     "Report what you actually found to the CEO."),
    ("sales", "Assessing customer impact",
     "Assess what this situation means for customers and revenue:\n\n\"{text}\"\n\n"
     "Look up any account that is affected, quantify the exposure in money and "
     "renewal timing, and report to the CEO with a recommended action."),
    ("ceo", "Deciding the response",
     "You now have engineering's findings and sales' read on the situation:\n\n\"{text}\"\n\n"
     "Decide the company's response and approve it explicitly. Close out any ticket "
     "or task that this resolves, and tell the agent who needs to act next."),
    ("customer", "Reacting",
     "You have learned how your vendor is handling this situation:\n\n\"{text}\"\n\n"
     "React honestly, based on whether it affects you and how competently they "
     "handled it. Set state_delta.satisfaction to reflect your revised view."),
    ("investor", "Assessing business impact",
     "This situation has just been handled by the company:\n\n\"{text}\"\n\n"
     "Pull the revenue and customer numbers, then record your judgement of the "
     "financial exposure and of how competently leadership responded."),
]


def build_custom_event(text: str, submitter: str = "") -> EventDefinition:
    """Turn a free-text situation into a runnable workflow.

    `submitter` names whoever sent it, for situations that arrived through the
    contact form rather than being typed straight into the dashboard. It is
    prepended to what the agents read, but deliberately kept out of the title
    and summary: those are cut from the front of the string, so a sender line
    there would leave every event card reading "A message arrived from…".
    """
    situation = " ".join(text.split())[:500]
    if not situation:
        raise ValueError("Describe the situation before running it.")

    # A short title for the card, cut at a word boundary rather than mid-word.
    title = situation if len(situation) <= 46 else situation[:46].rsplit(" ", 1)[0] + "…"

    read_by_agents = situation
    if submitter:
        read_by_agents = (
            f"A message arrived through the website contact form.\n"
            f"From: {submitter}\n\n{situation}"
        )

    return EventDefinition(
        key="custom",
        title=title,
        summary=situation,
        priority="high",
        icon="custom",
        steps=[
            Step(actor=actor, label=label, task=task.format(text=read_by_agents))
            for actor, label, task in CUSTOM_STEPS
        ],
    )


CATALOG: dict[str, EventDefinition] = {
    CUSTOMER_COMPLAINT.key: CUSTOMER_COMPLAINT,
}


def get(key: str) -> EventDefinition:
    if key not in CATALOG:
        raise KeyError(f"Unknown event '{key}'. Available: {', '.join(CATALOG)}")
    return CATALOG[key]


def catalog() -> list[dict]:
    return [e.as_dict() for e in CATALOG.values()]
