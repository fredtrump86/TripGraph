from __future__ import annotations

from typing import TypedDict

from app.models import Attraction, Hotel, TripPlan, TripRequest, WeatherInfo


class TravelState(TypedDict, total=False):
    """四个 Agent 在 LangGraph 中共享的最小状态。"""

    request: TripRequest
    attractions: list[Attraction]
    weather: list[WeatherInfo]
    hotels: list[Hotel]
    plan: TripPlan
