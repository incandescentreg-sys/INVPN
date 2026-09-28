"""Public catalogue endpoints (plans)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import PlanSvc
from app.schemas.plan import PlanRead
from app.utils.ids import to_uuid

router = APIRouter(prefix="/plans", tags=["plans"])

@router.get("", response_model=list[PlanRead])
async def list_plans(plans: PlanSvc) -> list[PlanRead]:
    """Active tariffs. Prices come from the DB, never from code."""
    return [PlanRead.model_validate(p) for p in await plans.list_active()]

@router.get("/{plan_id}", response_model=PlanRead)
async def get_plan(plan_id: str, plans: PlanSvc) -> PlanRead:
    from app.utils.exceptions import NotFoundError

    try:

        plan = await plans.get(to_uuid(plan_id))
    except ValueError as exc:
        raise NotFoundError("Тариф не найден") from exc
    return PlanRead.model_validate(plan)