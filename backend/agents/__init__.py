"""Registry of the five characters."""
from backend.agents.base import AgentProfile
from backend.agents.ceo import PROFILE as CEO
from backend.agents.customer import PROFILE as CUSTOMER
from backend.agents.developer import PROFILE as DEVELOPER
from backend.agents.investor import PROFILE as INVESTOR
from backend.agents.sales import PROFILE as SALES

REGISTRY: dict[str, AgentProfile] = {
    p.name: p for p in (CEO, SALES, DEVELOPER, CUSTOMER, INVESTOR)
}

# Display order on the dashboard.
ORDER = ["ceo", "sales", "developer", "customer", "investor"]


def get(name: str) -> AgentProfile:
    return REGISTRY[name]


def roster() -> list[dict]:
    return [REGISTRY[n].as_dict() for n in ORDER]
