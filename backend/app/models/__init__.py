"""ORM models. Importing this package registers every table on Base.metadata."""

from app.models.base import GUID, JSON, Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.notification import ExpiryReminder, Notification
from app.models.payment import Payment, PaymentEvent
from app.models.plan import Plan, plan_payload
from app.models.server import VpnServer
from app.models.subscription import Subscription, SubscriptionEvent
from app.models.user import User
from app.models.vpn_client import VpnClient

__all__ = [
    "GUID",
    "JSON",
    "Base",
    "ExpiryReminder",
    "Notification",
    "Payment",
    "PaymentEvent",
    "Plan",
    "Subscription",
    "SubscriptionEvent",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "VpnClient",
    "VpnServer",
    "plan_payload",
    "utcnow",
]
