"""Payment data access."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.enums import PaymentStatus
from app.models.payment import Payment, PaymentEvent
from app.utils.time import now


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _query(self) -> Select[tuple[Payment]]:
        return select(Payment).options(selectinload(Payment.plan), selectinload(Payment.user))

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return await self._session.scalar(self._query().where(Payment.id == payment_id))

    async def get_for_update(self, payment_id: uuid.UUID) -> Payment | None:
        return await self._session.scalar(self._query().where(Payment.id == payment_id).with_for_update())

    async def get_by_provider_id(self, provider: str, external_id: str) -> Payment | None:
        return await self._session.scalar(
            self._query().where(
                Payment.provider == provider, Payment.provider_payment_id == external_id
            )
        )

    async def get_by_idempotency(self, user_id: uuid.UUID, key: str) -> Payment | None:
        """Reuse the existing order when the user taps "pay" twice."""
        return await self._session.scalar(
            self._query().where(Payment.user_id == user_id, Payment.idempotency_key == key)
        )

    async def create(self, **fields: object) -> Payment:
        payment = Payment(**fields)  # type: ignore[arg-type]
        self._session.add(payment)
        await self._session.flush()
        return payment

    async def list_all(
        self,
        *,
        user_id: uuid.UUID | None = None,
        status: PaymentStatus | None = None,
        provider: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Payment]:
        stmt = self._query()
        if user_id:
            stmt = stmt.where(Payment.user_id == user_id)
        if status:
            stmt = stmt.where(Payment.status == status)
        if provider:
            stmt = stmt.where(Payment.provider == provider)
        stmt = stmt.order_by(Payment.created_at.desc()).limit(limit).offset(offset)
        return (await self._session.scalars(stmt)).all()

    async def list_pending(self, *, older_than_seconds: int = 60, limit: int = 50) -> Sequence[Payment]:
        """Payments still unresolved — candidates for gateway reconciliation."""
        cutoff = now() - dt.timedelta(seconds=older_than_seconds)
        stmt = (
            self._query()
            .where(Payment.status == PaymentStatus.PENDING, Payment.provider_payment_id.is_not(None))
            .where(Payment.created_at <= cutoff)
            .order_by(Payment.created_at)
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def mark_succeeded(self, payment: Payment, *, paid_at: dt.datetime | None = None) -> Payment:
        payment.status = PaymentStatus.SUCCEEDED
        payment.paid_at = paid_at or now()
        payment.failed_at = None
        payment.error_message = None
        await self._session.flush()
        return payment

    async def mark_status(
        self, payment: Payment, status: PaymentStatus, *, provider_status: str | None = None
    ) -> Payment:
        payment.status = status
        if status == PaymentStatus.SUCCEEDED and payment.paid_at is None:
            payment.paid_at = now()
        if status in (PaymentStatus.FAILED, PaymentStatus.CANCELLED):
            payment.failed_at = now()
        if provider_status:
            payment.provider_status = provider_status
        await self._session.flush()
        return payment

    async def attach_subscription(self, payment: Payment, subscription_id: uuid.UUID) -> Payment:
        payment.subscription_id = subscription_id
        await self._session.flush()
        return payment

    async def set_raw(self, payment: Payment, payload: dict[str, Any] | None) -> None:
        payment.raw_payload = payload
        await self._session.flush()

    # -- aggregates ------------------------------------------------------ #
    async def revenue_total(self, *, since: dt.datetime | None = None) -> dict[str, int]:
        stmt = select(
            func.coalesce(func.sum(Payment.amount_kopeks), 0),
            func.count(Payment.id),
        ).where(Payment.status == PaymentStatus.SUCCEEDED)
        if since:
            stmt = stmt.where(Payment.paid_at >= since)
        row = (await self._session.execute(stmt)).one()
        return {"total_kopeks": int(row[0] or 0), "count": int(row[1] or 0)}

    async def revenue_by_day(self, *, days: int = 14) -> list[dict[str, Any]]:
        since = now() - dt.timedelta(days=days)
        stmt = (
            select(func.date(Payment.paid_at), func.sum(Payment.amount_kopeks), func.count(Payment.id))
            .where(Payment.status == PaymentStatus.SUCCEEDED, Payment.paid_at >= since)
            .group_by(func.date(Payment.paid_at))
            .order_by(func.date(Payment.paid_at))
        )
        rows = (await self._session.execute(stmt)).all()
        return [{"date": str(r[0]), "total_kopeks": int(r[1] or 0), "count": int(r[2] or 0)} for r in rows]

    async def count_by_status(self) -> dict[str, int]:
        stmt = select(Payment.status, func.count(Payment.id)).group_by(Payment.status)
        rows = (await self._session.execute(stmt)).all()
        return {str(status): int(count) for status, count in rows}

    # -- events ---------------------------------------------------------- #
    async def log_event(
        self,
        *,
        provider: str,
        event_type: str,
        external_id: str | None = None,
        payload: dict[str, Any] | None = None,
        signature_ok: bool | None = None,
        error: str | None = None,
    ) -> PaymentEvent:
        event = PaymentEvent(
            provider=provider,
            event_type=event_type,
            external_id=external_id,
            payload=payload,
            signature_ok=signature_ok,
            error=error,
        )
        self._session.add(event)
        await self._session.flush()
        return event
