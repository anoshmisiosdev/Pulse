"""SQLAlchemy models. Import side effects register them on ``Base.metadata``."""

from app.models.billing import Subscription
from app.models.business import Business, User
from app.models.campaign import (
    AutomationRule,
    Campaign,
    CampaignSend,
    RecoveryAttribution,
)
from app.models.chat import ChatConversation, ChatMessage
from app.models.competitor_price import (
    CompetitorPriceCompetitor,
    CompetitorPriceObservation,
    CompetitorPriceResearchRun,
    CompetitorPriceSource,
    CompetitorPriceWatch,
)
from app.models.customer import (
    Customer,
    CustomerIdentity,
    EngagementEvent,
    RiskScore,
    Transaction,
    Visit,
)
from app.models.generation import AuditLog, GenerationLog
from app.models.integration import IntegrationConnection, ProviderWebhookEvent, SyncRun
from app.models.knowledge import BusinessKnowledge
from app.models.social import (
    BrandKitVersion,
    CompanyContextItem,
    PostReviewEvent,
    SocialCampaign,
    SocialComment,
    SocialPost,
)
from app.models.team import TeamInvite
from app.models.visitor import VisitorEvent, VisitorIdentifier, VisitorProfile
from app.models.waitlist import WaitlistSignup
from app.models.webhooks import WebhookDelivery, WebhookEndpoint

__all__ = [
    "TeamInvite",
    "WebhookEndpoint",
    "WebhookDelivery",
    "AuditLog",
    "GenerationLog",
    "ChatConversation",
    "ChatMessage",
    "BusinessKnowledge",
    "BrandKitVersion",
    "CompanyContextItem",
    "SocialCampaign",
    "SocialPost",
    "PostReviewEvent",
    "SocialComment",
    "Business",
    "User",
    "IntegrationConnection",
    "SyncRun",
    "Customer",
    "CustomerIdentity",
    "Transaction",
    "Visit",
    "EngagementEvent",
    "RiskScore",
    "ProviderWebhookEvent",
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
    "WaitlistSignup",
    "VisitorProfile",
    "VisitorIdentifier",
    "VisitorEvent",
]
