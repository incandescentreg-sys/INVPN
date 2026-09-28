"""Payment orchestration.

`confirm_payment()` is the only place that turns money into access. It is
idempotent and safe to call from a webhook, a redirect callback, or a cron
reconciliation pass — the row lock plus the SUCCEEDED check guarantee a single
subscription is ever issued per payment.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import payment_settings, telegram_settings
from app.enums import ClientStatus, PaymentStatus, SubscriptionStatus
from app.logging_config import get_logger
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.user import User
from app.payments import get_provider
from app.payments.base import CreatePaymentRequest, PaymentIntent, PaymentProvider
from app.repositories.payment import PaymentRepository
from app.repositories.plan import PlanRepository
from app.repositories.subscription import SubscriptionRepository
from app.repositories.user import UserRepository
from app.services.notification import NotificationService
from app.services.server import ServerService
from app.services.subscription import SubscriptionService
from app.services.vpn import VpnService
from app.utils.exceptions import NotFoundError, PaymentError
from app.utils.money import format_money

log = get_logger(__name__)


class PaymentService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        provider: PaymentProvider | None = None,
        bot: object | None = None,
    ) -> None:
        self._session = session
        self._payments = PaymentRepository(session)
        self._plans = PlanRepository(session)
        self._subs = SubscriptionRepository(session)
        self._users = UserRepository(session)
        self._subscriptions = SubscriptionService(session)
        self._servers = ServerService(session)
        self._vpn = VpnService(session)
        self._notifications = NotificationService(session, bot=bot)
        self._provider = provider or get_provider(payment_settings.provider)

    # ------------------------------------------------------------------ #
    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def get_subscription(self, payment: Payment) -> Any | None:
        """Subscription attached to a payment, if any."""
        if not payment.subscription_id:
            return None
        return await self._subs.get(payment.subscription_id)

    # ------------------------------------------------------------------ #
    async def create_payment(
        self, *, user: User, plan: Plan, idempotency_key: str | None = None
    ) -> Payment:
        """Create (or reuse) an order and ask the gateway for a payment URL."""
        key = idempotency_key or f"{user.id}-{plan.id}-{plan.price_kopeks}"

        existing = await self._payments.get_by_idempotency(user.id, key)
        if existing is not None and existing.provider_payment_id:
            if existing.status == PaymentStatus.PENDING:
                intent = await self._provider.get_status(existing.provider_payment_id)
                if intent.status == PaymentStatus.SUCCEEDED:
                    return await self.confirm_payment(existing.id, intent=intent)
                if intent.confirmation_url:
                    existing.confirmation_url = intent.confirmation_url
                    await self._session.flush()
                return existing
            if existing.status == PaymentStatus.SUCCEEDED:
                return existing

        subscription = await self._subscriptions.create_pending(
            user=user, plan=plan, amount_kopeks=plan.price_kopeks
        )

        payment: Payment | None = existing or await self._payments.create(
            user_id=user.id,
            plan_id=plan.id,
            subscription_id=subscription.id,
            provider=self._provider.name,
            idempotency_key=key,
            amount_kopeks=plan.price_kopeks,
            currency=plan.currency or payment_settings.currency,
            description=plan.title,
            status=PaymentStatus.PENDING,
        )
        if existing is not None:
            # Reusing an order: make sure it is linked to this plan.
            existing.subscription_id = existing.subscription_id or subscription.id
            await self._session.flush()
        else:
            try:
                await self._session.flush()
            except IntegrityError:
                # Concurrent double-tap — reuse the row created by the other request.
                await self._session.rollback()
                concurrent = await self._payments.get_by_idempotency(user.id, key)
                if concurrent is None:  # pragma: no cover
                    raise PaymentError("Не удалось создать платёж") from None
                return concurrent

        if payment is None:  # pragma: no cover - create() always returns a row
            raise PaymentError("Не удалось создать платёж")

        request = CreatePaymentRequest(
            amount_kopeks=plan.price_kopeks,
            currency=plan.currency or payment_settings.currency,
            description=plan.title,
            idempotency_key=payment.idempotency_key,
            return_url=payment_settings.return_url or telegram_settings.webapp_url,
            metadata={
                "user_id": str(user.id),
                "plan_code": plan.code,
                "subscription_id": str(subscription.id),
                "payment_id": str(payment.id),
            },
        )
        intent = await self._provider.create_payment(request)

        if payment is None:  # pragma: no cover - create() always returns a row
            raise PaymentError("Не удалось создать платёж")

        payment.provider_payment_id = intent.provider_payment_id
        payment.confirmation_url = intent.confirmation_url
        payment.provider_status = str(intent.status)
        payment.raw_payload = intent.raw
        await self._session.flush()

        log.info(
            "payment.created",
            payment_id=str(payment.id),
            plan=plan.code,
            amount=format_money(plan.price_kopeks, plan.currency),
        )
        return payment

    # ------------------------------------------------------------------ #
    async def confirm_payment(
        self, payment_id: uuid.UUID, *, intent: PaymentIntent | None = None
    ) -> Payment:
        """Mark paid and provision access. Idempotent."""
        payment = await self._payments.get_for_update(payment_id)
        if payment is None:
            raise NotFoundError("Платёж не найден")

        if payment.status == PaymentStatus.SUCCEEDED:
            log.info("payment.already_confirmed", payment_id=str(payment_id))
            await self._ensure_provisioned(payment)
            return payment

        if intent is not None:
            if intent.amount_kopeks and intent.amount_kopeks != payment.amount_kopeks:
                await self._payments.mark_status(
                    payment, PaymentStatus.FAILED, provider_status=str(intent.status)
                )
                payment.error_message = (
                    f"Сумма не совпадает: ожидалось {payment.amount_kopeks}, получено {intent.amount_kopeks}"
                )
                await self._session.flush()
                log.warning("payment.amount_mismatch", payment_id=str(payment_id))
                return payment
            payment.provider_status = str(intent.status)

        await self._payments.mark_succeeded(payment)
        log.info(
            "payment.succeeded",
            payment_id=str(payment.id),
            provider=payment.provider,
            external=payment.provider_payment_id,
        )
        await self._ensure_provisioned(payment)
        await self._notify_success(payment)
        return payment

    async def _notify_success(self, payment: Payment) -> None:
        """Tell the user their access is live (best effort — never fails a payment)."""
        try:
            user = await self._users.get(payment.user_id)
            if user is None or user.is_banned:
                return
            title = payment.description or "Подписка"
            await self._notifications.payment_success(
                user, plan_title=title, amount_kopeks=payment.amount_kopeks
            )
        except Exception as exc:
            log.warning("payment.notify_failed", payment_id=str(payment.id), error=str(exc)[:200])

    async def _ensure_provisioned(self, payment: Payment) -> None:
        """Activate the subscription and push the config to Xray."""
        if not payment.subscription_id:
            log.error("payment.subscription_missing", payment_id=str(payment.id))
            return

        subscription = await self._subs.get(payment.subscription_id)
        if subscription is None:
            log.error("payment.subscription_not_found", payment_id=str(payment.id))
            return

        if subscription.status == SubscriptionStatus.PENDING:
            server = await self._servers.pick(subscription.plan.server_id if subscription.plan else None)
            if server is not None and subscription.server_id is None:
                subscription.server_id = server.id
            await self._subscriptions.activate(subscription)
        elif subscription.status in (SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELLED):
            # Late payment for a lapsed subscription → renew instead of activate.
            await self._subscriptions.activate(subscription)

        if payment.subscription_id != subscription.id:  # pragma: no cover - defensive
            payment.subscription_id = subscription.id

        await self._provision(subscription)

    async def _provision(self, subscription: Any) -> None:
        """Issue the first config and sync Xray. Failures never lose the payment."""
        server = subscription.server
        if server is None:
            server = await self._servers.pick()
            if server is None:
                log.error("payment.no_server_available", subscription_id=str(subscription.id))
                return
            subscription.server_id = server.id
            await self._session.flush()

        try:
            client = await self._vpn.ensure_primary_client(subscription, server)
            if client.status != ClientStatus.ACTIVE:
                await self._vpn.sync_server(server)
        except Exception as exc:
            # The user has paid; access will be granted by the next sync/cron run.
            log.error(
                "payment.provision_failed",
                subscription_id=str(subscription.id),
                error=str(exc)[:300],
            )
            subscription.note = f"provision error: {exc}"[:255]

    # ------------------------------------------------------------------ #
    async def handle_webhook(self, payload: bytes, headers: dict[str, str]) -> Payment | None:
        event = await self._provider.verify_webhook(payload, headers)
        await self._payments.log_event(
            provider=event.provider,
            event_type=event.event_type,
            external_id=event.provider_payment_id,
            payload=event.raw,
            signature_ok=event.signature_valid,
        )

        payment = await self._payments.get_by_provider_id(
            self._provider.name, event.provider_payment_id
        )
        if payment is None:
            log.warning(
                "payment.webhook_unknown_payment", external_id=event.provider_payment_id
            )
            return None

        if event.status == PaymentStatus.SUCCEEDED:
            intent = PaymentIntent(
                provider=event.provider,
                provider_payment_id=event.provider_payment_id,
                amount_kopeks=event.amount_kopeks or payment.amount_kopeks,
                currency=payment.currency,
                status=event.status,
                raw=event.raw,
            )
            return await self.confirm_payment(payment.id, intent=intent)

        if event.status in (PaymentStatus.FAILED, PaymentStatus.CANCELLED):
            await self._payments.mark_status(payment, event.status, provider_status=event.event_type)
            return payment

        await self._payments.set_raw(payment, event.raw)
        return payment

    async def poll_status(self, payment_id: uuid.UUID) -> Payment:
        """Fallback when webhooks are unavailable — used by the return-URL handler."""
        payment = await self._payments.get(payment_id)
        if payment is None:
            raise NotFoundError("Платёж не найден")
        if payment.status != PaymentStatus.PENDING or not payment.provider_payment_id:
            return payment

        intent = await self._provider.get_status(payment.provider_payment_id)
        await self._payments.set_raw(payment, intent.raw)
        if intent.status == PaymentStatus.SUCCEEDED:
            return await self.confirm_payment(payment.id, intent=intent)
        if intent.status in (PaymentStatus.FAILED, PaymentStatus.CANCELLED):
            await self._payments.mark_status(payment, intent.status, provider_status=str(intent.status))
        return payment

    async def reconcile_pending(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Cron safety net: ask the gateway about every unresolved payment."""
        results: list[dict[str, Any]] = []
        for payment in await self._payments.list_pending(limit=limit):
            entry: dict[str, Any] = {"payment_id": str(payment.id)}
            try:
                updated = await self.poll_status(payment.id)
                entry.update({"status": str(updated.status), "ok": True})
            except Exception as exc:
                entry.update({"ok": False, "error": str(exc)[:200]})
            results.append(entry)
        if results:
            log.info("payment.reconciled", count=len(results))
        return results

    # -- refunds -------------------------------------------------------- #
    async def refund(
        self, payment_id: uuid.UUID, *, amount_kopeks: int | None = None, actor: str = "admin"
    ) -> Payment:
        payment = await self._payments.get(payment_id)
        if payment is None:
            raise NotFoundError("Платёж не найден")
        if not payment.provider_payment_id:
            raise PaymentError("У платежа нет идентификатора в платёжной системе")
        if payment.status != PaymentStatus.SUCCEEDED:
            raise PaymentError(f"Возврат возможен только для оплаченных платежей (статус: {payment.status})")

        result = await self._provider.refund(payment.provider_payment_id, amount_kopeks)
        refunded = amount_kopeks or payment.amount_kopeks
        payment.refunded_kopeks += refunded
        if payment.refunded_kopeks >= payment.amount_kopeks:
            payment.status = PaymentStatus.REFUNDED
        else:
            payment.status = PaymentStatus.PARTIALLY_REFUNDED
        payment.raw_payload = result.raw
        await self._session.flush()
        log.info("payment.refunded", payment_id=str(payment.id), amount=refunded, actor=actor)
        return payment

    # -- reads ---------------------------------------------------------- #
    async def get(self, payment_id: uuid.UUID) -> Payment:
        payment = await self._payments.get(payment_id)
        if payment is None:
            raise NotFoundError("Платёж не найден")
        return payment

    async def list_for_user(self, user_id: uuid.UUID, *, limit: int = 20) -> list[Payment]:
        return list(await self._payments.list_all(user_id=user_id, limit=limit))

    async def stats(self) -> dict[str, Any]:
        total = await self._payments.revenue_total()
        return {
            "revenue_kopeks": total["total_kopeks"],
            "successful_count": total["count"],
            "by_status": await self._payments.count_by_status(),
            "by_day": await self._payments.revenue_by_day(),
        }
