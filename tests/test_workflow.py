import asyncio
from datetime import date

import pytest

from app.graph.agents import (
    AttractionResearch,
    LLMTravelAgentSuite,
    WeatherResearch,
)
from app.graph.workflow import build_travel_graph
from app.models import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    Location,
    Meal,
    ResearchBundle,
    TripPlan,
    TripRequest,
    WeatherInfo,
)


class FakeStructuredModel:
    def __init__(self, response: dict) -> None:
        self.method = ""
        self.messages = []
        self.response = response

    def with_structured_output(self, _schema, *, method: str):
        self.method = method
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return self.response


class FakeAmapService:
    async def search_pois(self, city: str, keywords: str) -> str:
        return (
            '{"pois":[{"id":"B001","name":"西湖","address":"杭州市西湖区",'
            '"typecode":"110000"}]}'
        )

    async def get_poi_details(self, poi_ids: list[str]) -> list[str]:
        assert poi_ids == ["B001"]
        return [
            '{"id":"B001","name":"西湖","address":"杭州市西湖区",'
            '"location":"120.131487,30.196338","rating":"4.9"}'
        ]


class FakeAgentSuite:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.attractions_complete = False
        self.weather_complete = False

    async def research_attractions(self, request: TripRequest) -> list[Attraction]:
        self.calls.append("attractions")
        await asyncio.sleep(0)
        self.attractions_complete = True
        return [
            Attraction(
                name="西湖",
                address="杭州市西湖区",
                location=Location(longitude=120.15, latitude=30.25),
                visit_duration=180,
                description="湖泊与文化景观",
                ticket_price=0,
            )
        ]

    async def research_weather(self, request: TripRequest) -> list[WeatherInfo]:
        assert self.attractions_complete
        self.calls.append("weather")
        await asyncio.sleep(0)
        self.weather_complete = True
        return [
            WeatherInfo(
                date=request.start_date,
                day_weather="晴",
                night_weather="多云",
                day_temp=30,
                night_temp=24,
                wind_direction="东风",
                wind_power="3级",
            )
        ]

    async def research_hotels(self, request: TripRequest) -> list[Hotel]:
        assert self.weather_complete
        self.calls.append("hotels")
        return [Hotel(name="测试酒店", address="湖滨", estimated_cost=400)]

    async def draft(self, request: TripRequest, research: ResearchBundle) -> TripPlan:
        self.calls.append("planner")
        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=[
                DayPlan(
                    date=request.start_date,
                    day_index=0,
                    description="西湖一日游",
                    transportation=request.transportation,
                    accommodation=request.accommodation,
                    hotel=research.hotels[0],
                    attractions=research.attractions,
                    meals=[
                        Meal(type="lunch", name="杭帮菜", estimated_cost=80),
                    ],
                )
            ],
            weather_info=research.weather,
            overall_suggestions="提前预约",
            budget=Budget(
                total_attractions=0,
                total_hotels=400,
                total_meals=80,
                total_transportation=50,
                total=530,
            ),
        )


@pytest.mark.asyncio
async def test_graph_contains_only_reference_agents_and_planner() -> None:
    agents = FakeAgentSuite()
    graph = build_travel_graph(agents)
    request = TripRequest(
        city="杭州",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        travel_days=1,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=["自然风光"],
    )

    result = await graph.ainvoke({"request": request})

    assert result["plan"].city == "杭州"
    assert agents.calls == ["attractions", "weather", "hotels", "planner"]
    assert set(result) == {"request", "attractions", "weather", "hotels", "plan"}


@pytest.mark.asyncio
async def test_live_agents_use_function_calling_for_compatible_llm_endpoints() -> None:
    model = FakeStructuredModel({"items": []})
    agents = LLMTravelAgentSuite(model=model, amap=None)

    result = await agents._structured(AttractionResearch, "system", "user")

    assert model.method == "function_calling"
    assert result.items == []


@pytest.mark.asyncio
async def test_deepseek_json_mode_receives_the_pydantic_schema() -> None:
    model = FakeStructuredModel({"items": []})
    agents = LLMTravelAgentSuite(model=model, amap=None, structured_method="json_mode")

    await agents._structured(WeatherResearch, "system", "user")

    assert model.method == "json_mode"
    assert "JSON Schema" in model.messages[0].content
    assert "items" in model.messages[0].content


@pytest.mark.asyncio
async def test_attraction_agent_fills_coordinates_from_mcp_poi_detail() -> None:
    model = FakeStructuredModel(
        {
            "items": [
                {
                    "poi_id": "B001",
                    "name": "西湖",
                    "address": "杭州市西湖区",
                    "location": None,
                    "visit_duration": 180,
                    "description": "世界文化遗产",
                    "category": "风景名胜",
                    "rating": 4.9,
                    "photos": [],
                    "image_url": None,
                    "ticket_price": 0,
                }
            ]
        }
    )
    agents = LLMTravelAgentSuite(model=model, amap=FakeAmapService())
    request = TripRequest(
        city="杭州",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        travel_days=1,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=["历史文化"],
    )

    attractions = await agents.research_attractions(request)

    assert len(attractions) == 1
    assert attractions[0].poi_id == "B001"
    assert attractions[0].location.longitude == pytest.approx(120.131487)
    assert attractions[0].location.latitude == pytest.approx(30.196338)
