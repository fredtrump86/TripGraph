from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import LiveModeConfigurationError, get_settings
from app.graph.agents import DemoTravelAgentSuite, LLMTravelAgentSuite
from app.graph.workflow import build_travel_graph
from app.models import TripPlanResponse, TripRequest
from app.services.mcp_maps import AmapMCPService, MCPServiceError

logger = logging.getLogger(__name__)
settings = get_settings()
static_dir = Path(__file__).parent / "static"

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="由 LangGraph StateGraph 编排的多 Agent 智能旅行规划服务",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@lru_cache
def get_runtime_graph():
    if settings.demo_mode:
        agents = DemoTravelAgentSuite()
    else:
        settings.validate_live_mode()
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
            max_retries=2,
            extra_body=settings.llm_extra_body,
        )
        amap = AmapMCPService(settings.amap_api_key, settings.amap_mcp_url)
        agents = LLMTravelAgentSuite(
            model=model,
            amap=amap,
            structured_method=settings.llm_structured_method,
        )
    return build_travel_graph(agents)


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(
        static_dir / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/result", include_in_schema=False)
async def result_page() -> FileResponse:
    return await home()


@app.get("/health", tags=["系统"])
async def health() -> dict[str, object]:
    return {
        "status": "healthy",
        "service": "trip-planner",
        "framework": "LangGraph",
        "agents": ["景点搜索", "天气查询", "酒店推荐", "行程规划"],
    }


@app.get("/api/maps/config", tags=["地图"])
async def map_config(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return {
        "enabled": bool(settings.amap_js_key and settings.amap_js_security_code),
        "key": settings.amap_js_key,
        "security_code": settings.amap_js_security_code,
    }


@lru_cache(maxsize=256)
def _search_unsplash_photo(name: str, access_key: str) -> str | None:
    query = urlencode({"query": f"{name} China landmark", "per_page": 1})
    request = Request(
        f"https://api.unsplash.com/search/photos?{query}",
        headers={
            "Authorization": f"Client-ID {access_key}",
            "Accept-Version": "v1",
            "User-Agent": "LangGraphTripPlanner/1.3",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return None
    results = payload.get("results", [])
    if not results:
        return None
    return results[0].get("urls", {}).get("regular")


@app.get("/api/poi/photo", tags=["POI"])
async def attraction_photo(name: str = Query(min_length=1, max_length=100)) -> dict[str, object]:
    photo_url = None
    if settings.unsplash_access_key:
        photo_url = await asyncio.to_thread(
            _search_unsplash_photo,
            name.strip(),
            settings.unsplash_access_key,
        )
    return {
        "success": True,
        "message": "获取图片成功" if photo_url else "未配置图片服务或未找到图片，使用本地占位图",
        "data": {"name": name, "photo_url": photo_url},
    }


@app.post("/api/trip/plan", response_model=TripPlanResponse, tags=["旅行规划"])
async def plan_trip(request: TripRequest) -> TripPlanResponse:
    try:
        result = await get_runtime_graph().ainvoke({"request": request})
        return TripPlanResponse(
            success=True,
            message="旅行计划生成成功",
            data=result["plan"],
        )
    except LiveModeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MCPServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("旅行计划生成失败")
        raise HTTPException(status_code=500, detail="旅行计划生成失败，请稍后重试。") from exc
