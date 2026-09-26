from datetime import datetime, timezone

from models.schemas import Case


def create_sample_case() -> Case:
    created_at = datetime(2026, 9, 26, 13, 0, 0, tzinfo=timezone.utc)
    return Case(
        case_id="CASE-2026-001",
        case_name="PipeTrekker 管内点検",
        customer_name="サンプル株式会社",
        end_user_name=None,
        status="OPEN",
        requested_products=["PipeTrekker"],
        created_at=created_at,
        updated_at=created_at,
    )


def sample_case_json() -> str:
    return create_sample_case().model_dump_json(indent=2)
