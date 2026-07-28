from datetime import date

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import Attraction, TripRequest


def test_trip_request_uses_the_reference_project_fields() -> None:
    request = TripRequest(
        city="杭州",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 3),
        travel_days=3,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=["历史文化", "美食"],
        free_text_input="行程不要太满",
    )

    assert request.travel_days == 3
    assert set(request.model_dump()) == {
        "city",
        "start_date",
        "end_date",
        "travel_days",
        "transportation",
        "accommodation",
        "preferences",
        "free_text_input",
    }


def test_trip_request_rejects_reversed_dates() -> None:
    with pytest.raises(ValidationError, match="结束日期不能早于开始日期"):
        TripRequest(
            city="杭州",
            start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 1),
            travel_days=1,
            transportation="公共交通",
            accommodation="经济型酒店",
        )


def test_trip_request_rejects_inconsistent_travel_days() -> None:
    with pytest.raises(ValidationError, match="旅行天数必须与日期范围一致"):
        TripRequest(
            city="杭州",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 3),
            travel_days=2,
            transportation="公共交通",
            accommodation="经济型酒店",
        )


def test_attraction_requires_map_coordinates() -> None:
    with pytest.raises(ValidationError, match="location"):
        Attraction(
            name="西湖",
            address="杭州市西湖区",
            visit_duration=120,
            description="世界文化遗产",
        )


def test_deepseek_disables_thinking_for_forced_structured_output() -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-v4-flash",
    )

    assert settings.llm_extra_body == {"thinking": {"type": "disabled"}}
    assert settings.llm_structured_method == "json_mode"


def test_openai_does_not_receive_deepseek_request_options() -> None:
    settings = Settings(_env_file=None, llm_base_url="https://api.openai.com/v1")

    assert settings.llm_extra_body is None
    assert settings.llm_structured_method == "function_calling"
