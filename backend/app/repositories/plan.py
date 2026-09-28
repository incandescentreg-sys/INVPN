"""Plan catalogue data access."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan


class PlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, plan_id: uuid.UUID) -> Plan | None:
        return await self._session.get(Plan, plan_id)

    async def get_by_code(self, code: str) -> Plan | None:
        return await self._session.scalar(select(Plan).where(Plan.code == code))

    async def list_active(self) -> list[Plan]:
        stmt = (
            select(Plan)
            .where(Plan.is_active.is_(True))
            .order_by(Plan.sort_order, Plan.days)
        )
        return list((await self._session.scalars(stmt)).all())

    async def list_all(self) -> list[Plan]:
        stmt = select(Plan).order_by(Plan.sort_order, Plan.days)
        return list((await self._session.scalars(stmt)).all())

    async def create(self, **fields: object) -> Plan:
        plan = Plan(**fields)  # type: ignore[arg-type]
        self._session.add(plan)
        await self._session.flush()
        return plan

    async def update(self, plan_id: uuid.UUID, **fields: object) -> Plan | None:
        plan = await self.get(plan_id)
        if plan is None:
            return None
        for key, value in fields.items():
            if value is not None and hasattr(plan, key):
                setattr(plan, key, value)
        await self._session.flush()
        return plan

    async def set_active(self, plan_id: uuid.UUID, is_active: bool) -> Plan | None:
        plan = await self.get(plan_id)
        if plan is None:
            return None
        plan.is_active = is_active
        await self._session.flush()
        return plan

    async def upsert_by_code(self, **fields: object) -> Plan:
        code = str(fields.get("code", ""))
        plan = await self.get_by_code(code)
        if plan is None:
            plan = await self.create(**fields)
        else:
            return await self.update(plan.id, **fields) or plan
        return plan

    async def count_subscriptions(self, plan_id: uuid.UUID) -> int:
        from app.models.subscription import Subscription

        stmt = select(func.count()).select_from(Subscription).where(Subscription.plan_id == plan_id)
        return int(await self._session.scalar(stmt) or 0)

    async def next_sort_order(self) -> int:
        current = await self._session.scalar(select(func.max(Plan.sort_order)))
        return int(current or 0) + 10

    async def shift_sort_order(self, plan_id: uuid.UUID, delta: int) -> None:
        await self._session.execute(
            update(Plan).where(Plan.id == plan_id).values(sort_order=Plan.sort_order + delta)
        )
