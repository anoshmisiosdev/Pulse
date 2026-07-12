"""SQLAlchemy models. Import side effects register them on ``Base.metadata``."""

from app.models.billing import Subscription
from app.models.business import Business, User
from app.models.campaign import (
    AutomationRule,
    Campaign,
    CampaignSend,
    RecoveryAttribution,
)
from app.models.competitor_price import (
    CompetitorPriceCompetitor,
    CompetitorPriceObservation,
    CompetitorPriceResearchRun,
    CompetitorPriceSource,
    CompetitorPriceWatch,
)
from app.models.customer import (
    Customer,
    EngagementEvent,
    RiskScore,
    Transaction,
    Visit,
)
from app.models.integration import IntegrationConnection, SyncRun

__all__ = [
    "Business",
    "User",
    "IntegrationConnection",
    "SyncRun",
    "Customer",
    "Transaction",
    "Visit",
    "EngagementEvent",
    "RiskScore",
    "Campaign",
    "CampaignSend",
    "AutomationRule",
    "RecoveryAttribution",
    "Subscription",
    "CompetitorPriceResearchRun",
    "CompetitorPriceCompetitor",
    "CompetitorPriceSource",
    "CompetitorPriceObservation",
    "CompetitorPriceWatch",
]
