"""Plan catalogue + seeding from environment values."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import payment_settings, plan_seed_settings
from app.logging_config import get_logger
from app.models.plan import Plan, plan_payload
from app.repositories.plan import PlanRepository
from app.utils.exceptions import NotFoundError

log = get_logger(__name__)


class PlanService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = PlanRepository(session)

    async def list_active(self) -> list[Plan]:
        return await self._plans.list_active()

    async def list_all(self) -> list[Plan]:
        return await self._plans.list_all()

    async def get(self, plan_id: uuid.UUID) -> Plan:
        plan = await self._plans.get(plan_id)
        if plan is None:
            raise NotFoundError("Тариф не найден")
        return plan

    async def get_by_code(self, code: str) -> Plan | None:
        return await self._plans.get_by_code(code)

    async def create(self, **fields: Any) -> Plan:
        code = str(fields.get("code") or "")
        if await self._plans.get_by_code(code):
            raise ValueError(f"Тариф с кодом {code!r} уже существует")
        fields.setdefault("currency", payment_settings.currency)
        fields.setdefault("sort_order", await self._plans.next_sort_order())
        plan = await self._plans.create(**fields)
        log.info("plan.created", code=plan.code, price_kopeks=plan.price_kopeks)
        return plan

    async def update(self, plan_id: uuid.UUID, **fields: Any) -> Plan:
        plan = await self._plans.update(plan_id, **fields)
        if plan is None:
            raise NotFoundError("Тариф не найден")
        return plan

    async def set_active(self, plan_id: uuid.UUID, is_active: bool) -> Plan:
        plan = await self._plans.set_active(plan_id, is_active)
        if plan is None:
            raise NotFoundError("Тариф не найден")
        return plan

    async def delete(self, plan_id: uuid.UUID) -> bool:
        """Soft-delete: subscriptions keep referencing the plan."""
        plan = await self.get(plan_id)
        plan.is_active = False
        await self._session.flush()
        return True

    # ------------------------------------------------------------------ #
    async def seed_default(self) -> list[Plan]:
        """Create the starter tariff if the catalogue is empty.

        Price/title/duration come from .env (SEED_PLAN_30D_*), so nothing is
        hardcoded and the admin can edit the row afterwards.
        """
        existing = await self._plans.get_by_code("vpn_30d")
        if existing is not None:
            return [existing]

        plan = await self._plans.create(
            **plan_payload(
                code="vpn_30d",
                title=plan_seed_settings.plan_30d_title,
                days=plan_seed_settings.plan_30d_days,
                price_kopeks=plan_seed_settings.plan_30d_price,
                currency=payment_settings.currency,
                description="Безлимитный доступ к VPN, один конфиг, любые устройства",
                features=[
                    "VLESS + REALITY (защита от блокировок)",
                    "Без ограничения трафика",
                    "Можно установить на любое устройство",
                    "Поддержка 24/7",
                ],
                badge="Популярный",
                is_popular=True,
                sort_order=10,
            )
        )
        log.info("plan.seeded", code=plan.code, price_kopeks=plan.price_kopeks)
        return [plan]
