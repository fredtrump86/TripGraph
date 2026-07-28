from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Literal, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

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
from app.services.mcp_maps import AmapMCPService, MCPServiceError


class AgentSuite(Protocol):
    async def research_attractions(self, request: TripRequest) -> list[Attraction]: ...

    async def research_weather(self, request: TripRequest) -> list[WeatherInfo]: ...

    async def research_hotels(self, request: TripRequest) -> list[Hotel]: ...

    async def draft(self, request: TripRequest, research: ResearchBundle) -> TripPlan: ...


class AttractionCandidate(Attraction):
    """允许模型暂缺坐标，随后必须由 MCP POI 详情补齐。"""

    poi_id: str
    location: Location | None = None


class AttractionResearch(BaseModel):
    items: list[AttractionCandidate] = Field(default_factory=list)


class HotelResearch(BaseModel):
    items: list[Hotel] = Field(default_factory=list)


class WeatherResearch(BaseModel):
    items: list[WeatherInfo] = Field(default_factory=list)


class LLMTravelAgentSuite:
    """使用同一模型实例实现参考项目的四个专业 Agent。"""

    def __init__(
        self,
        model: Any,
        amap: AmapMCPService | None,
        structured_method: Literal["function_calling", "json_mode"] = "function_calling",
    ) -> None:
        self.model = model
        self.amap = amap
        self.structured_method = structured_method

    async def _structured(self, schema: type[BaseModel], system: str, user: str) -> BaseModel:
        if self.structured_method == "json_mode":
            schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            system = (
                f"{system}\n只输出一个符合下面 JSON Schema 的 JSON 对象，不要输出 Markdown 或解释：\n"
                f"{schema_json}"
            )
        runnable = self.model.with_structured_output(schema, method=self.structured_method)
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        result = await runnable.ainvoke(messages)
        if result is None:
            raise RuntimeError(f"{schema.__name__} 结构化输出为空")
        return result if isinstance(result, schema) else schema.model_validate(result)

    def _require_amap(self) -> AmapMCPService:
        if self.amap is None:
            raise RuntimeError("高德 MCP 服务未初始化")
        return self.amap

    async def research_attractions(self, request: TripRequest) -> list[Attraction]:
        keyword = request.preferences[0] if request.preferences else "景点"
        amap = self._require_amap()
        search_result = await amap.search_pois(request.city, keyword)
        limit = min(60, max(6, request.travel_days * 3))
        poi_ids = _extract_poi_ids(search_result)[:limit]
        if not poi_ids:
            raise MCPServiceError("高德 MCP 文本搜索没有返回可用的 POI ID。")
        detail_results = await amap.get_poi_details(poi_ids)
        result = await self._structured(
            AttractionResearch,
            (
                "你是景点搜索专家。根据用户偏好整理高德 MCP 搜索结果，最多返回"
                f"{limit}个景点。只能使用工具结果中的地点、地址、坐标、评分和 POI ID，"
                "必须原样保留 POI ID；不得编造地点；缺失门票价格时填写0。"
            ),
            _mcp_payload(
                request,
                {
                    "text_search": search_result,
                    "poi_details": detail_results,
                },
            ),
        )
        return _verified_attractions(result.items, detail_results)[:limit]

    async def research_weather(self, request: TripRequest) -> list[WeatherInfo]:
        mcp_result = await self._require_amap().get_weather(request.city)
        result = await self._structured(
            WeatherResearch,
            (
                "你是天气查询专家。把高德 MCP 返回的天气整理为逐日天气数组。"
                "不得修改日期、天气、温度、风向或风力，不得补造工具结果中没有的预报。"
            ),
            _mcp_payload(request, mcp_result),
        )
        return result.items

    async def research_hotels(self, request: TripRequest) -> list[Hotel]:
        mcp_result = await self._require_amap().search_pois(
            request.city,
            f"{request.accommodation}酒店",
        )
        result = await self._structured(
            HotelResearch,
            (
                "你是酒店推荐专家。根据高德 MCP 搜索结果整理最多5个酒店候选。"
                "只能使用工具结果中的真实酒店、地址、坐标、评分和类型；"
                "搜索结果没有价格时 estimated_cost 填0、price_range 留空。"
            ),
            _mcp_payload(request, mcp_result),
        )
        return result.items[:5]

    async def draft(self, request: TripRequest, research: ResearchBundle) -> TripPlan:
        result = await self._structured(
            TripPlan,
            (
                "你是行程规划专家。根据景点、天气和酒店研究结果生成完整旅行计划。"
                "日期必须连续并覆盖请求范围，day_index 从0开始。每天安排2至3个不重复景点，"
                "优先把相近景点放在同一天；每天包含早餐、午餐和晚餐，写明交通与住宿；"
                "景点必须完整保留研究结果中的 POI ID 和经纬度；"
                "天气只能使用研究结果，不能杜撰；必须给出总体建议和预算汇总。"
            ),
            json.dumps(
                {
                    "request": request.model_dump(mode="json"),
                    "research": research.model_dump(mode="json"),
                },
                ensure_ascii=False,
            ),
        )
        return _restore_verified_locations(TripPlan.model_validate(result), research.attractions)


class DemoTravelAgentSuite:
    """无密钥时运行同一个四节点 LangGraph 的演示数据套件。"""

    _centers = {
        "北京": (116.397, 39.909),
        "上海": (121.474, 31.230),
        "杭州": (120.155, 30.274),
        "成都": (104.066, 30.573),
        "广州": (113.264, 23.129),
        "西安": (108.940, 34.341),
    }

    async def research_attractions(self, request: TripRequest) -> list[Attraction]:
        longitude, latitude = self._centers.get(request.city, (116.397, 39.909))
        names = ["城市博物馆", "历史文化街区", "城市公园", "艺术中心", "滨水步道", "特色市集"]
        return [
            Attraction(
                name=f"{request.city}{names[index % len(names)]}{index + 1}（演示）",
                address=f"{request.city}演示地址{index + 1}号",
                location=Location(
                    longitude=longitude + index * 0.008,
                    latitude=latitude + (index % 3) * 0.006,
                ),
                visit_duration=120,
                description="内置演示景点，实时模式会替换为高德 MCP 查询结果。",
                category="景点",
                poi_id=f"demo-{request.city}-{index + 1}",
                ticket_price=20 if index % 2 else 0,
            )
            for index in range(max(6, request.travel_days * 2))
        ]

    async def research_weather(self, request: TripRequest) -> list[WeatherInfo]:
        return [
            WeatherInfo(
                date=request.start_date + timedelta(days=index),
                day_weather="晴间多云",
                night_weather="多云",
                day_temp=26,
                night_temp=18,
                wind_direction="东风",
                wind_power="2级",
            )
            for index in range(request.travel_days)
        ]

    async def research_hotels(self, request: TripRequest) -> list[Hotel]:
        longitude, latitude = self._centers.get(request.city, (116.397, 39.909))
        return [
            Hotel(
                name=f"{request.city}中心酒店（演示）",
                address=f"{request.city}市中心演示地址",
                location=Location(longitude=longitude, latitude=latitude),
                price_range="约400-450元/晚",
                rating="4.5",
                distance="距核心景点约2公里",
                type=request.accommodation,
                estimated_cost=420,
            )
        ]

    async def draft(self, request: TripRequest, research: ResearchBundle) -> TripPlan:
        hotel = research.hotels[0] if research.hotels else None
        days: list[DayPlan] = []
        for index in range(request.travel_days):
            attractions = research.attractions[index * 2 : index * 2 + 2]
            meals = [
                Meal(
                    type=meal_type,
                    name=f"{request.city}{label}推荐（演示）",
                    description=f"第{index + 1}天{label}演示推荐",
                    estimated_cost=cost,
                )
                for meal_type, label, cost in (
                    ("breakfast", "早餐", 25),
                    ("lunch", "午餐", 70),
                    ("dinner", "晚餐", 100),
                )
            ]
            days.append(
                DayPlan(
                    date=request.start_date + timedelta(days=index),
                    day_index=index,
                    description=f"第{index + 1}天城市探索与在地体验",
                    transportation=request.transportation,
                    accommodation=request.accommodation,
                    hotel=hotel,
                    attractions=attractions,
                    meals=meals,
                )
            )

        attraction_total = sum(item.ticket_price for day in days for item in day.attractions)
        hotel_total = (hotel.estimated_cost if hotel else 0) * max(request.travel_days - 1, 0)
        meal_total = sum(item.estimated_cost for day in days for item in day.meals)
        transport_total = 50 * request.travel_days
        budget = Budget(
            total_attractions=attraction_total,
            total_hotels=hotel_total,
            total_meals=meal_total,
            total_transportation=transport_total,
            total=attraction_total + hotel_total + meal_total + transport_total,
        )
        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=research.weather,
            overall_suggestions="当前为演示数据；配置 LLM 与高德 MCP 后可生成实时行程。",
            budget=budget,
        )


def _mcp_payload(request: TripRequest, result: object) -> str:
    return json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "amap_mcp_result": result,
        },
        ensure_ascii=False,
    )


def _extract_poi_ids(search_result: str) -> list[str]:
    try:
        payload = json.loads(search_result)
    except json.JSONDecodeError:
        return []
    pois = payload.get("pois", []) if isinstance(payload, dict) else []
    return list(
        dict.fromkeys(
            str(item["id"])
            for item in pois
            if isinstance(item, dict) and item.get("id")
        )
    )


def _parse_location(value: object) -> Location | None:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 2:
            return None
        try:
            return Location(longitude=float(parts[0]), latitude=float(parts[1]))
        except ValueError:
            return None
    if isinstance(value, dict):
        longitude = value.get("longitude", value.get("lng", value.get("lon")))
        latitude = value.get("latitude", value.get("lat"))
        if longitude is None or latitude is None:
            return None
        try:
            return Location(longitude=float(longitude), latitude=float(latitude))
        except (TypeError, ValueError):
            return None
    return None


def _detail_records(detail_results: list[str]) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for detail in detail_results:
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not payload.get("id"):
            continue
        location = _parse_location(payload.get("location"))
        if location is None:
            continue
        records[str(payload["id"])] = {**payload, "location": location}
    return records


def _verified_attractions(
    candidates: list[AttractionCandidate],
    detail_results: list[str],
) -> list[Attraction]:
    records = _detail_records(detail_results)
    verified: list[Attraction] = []
    for candidate in candidates:
        record = records.get(candidate.poi_id)
        if record is None:
            continue
        rating = candidate.rating
        if rating is None and record.get("rating") not in (None, ""):
            try:
                rating = float(record["rating"])
            except (TypeError, ValueError):
                rating = None
        verified.append(
            Attraction(
                **candidate.model_dump(exclude={"location", "rating", "image_url"}),
                location=record["location"],
                rating=rating,
                image_url=candidate.image_url or str(record.get("photo") or "") or None,
            )
        )
    if not verified:
        raise MCPServiceError("高德 MCP POI 详情没有返回可用坐标。")
    return verified


def _normalized_name(value: str) -> str:
    return "".join(value.casefold().split())


def _restore_verified_locations(plan: TripPlan, candidates: list[Attraction]) -> TripPlan:
    by_id = {item.poi_id: item for item in candidates if item.poi_id}
    by_name = {_normalized_name(item.name): item for item in candidates}
    days: list[DayPlan] = []
    for day in plan.days:
        attractions: list[Attraction] = []
        for item in day.attractions:
            canonical = by_id.get(item.poi_id) or by_name.get(_normalized_name(item.name))
            attractions.append(canonical or item)
        days.append(day.model_copy(update={"attractions": attractions}))
    return plan.model_copy(update={"days": days})
