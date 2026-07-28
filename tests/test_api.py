import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DEMO_MODE"] = "true"
os.environ["AMAP_API_KEY"] = "server-only-mcp-key"
os.environ["AMAP_JS_KEY"] = "test-js-key"
os.environ["AMAP_JS_SECURITY_CODE"] = "test-security-code"

from app.main import app  # noqa: E402


async def request(method: str, path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_health_endpoint_identifies_langgraph() -> None:
    response = await request("GET", "/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["framework"] == "LangGraph"
    assert response.json()["agents"] == ["景点搜索", "天气查询", "酒店推荐", "行程规划"]


@pytest.mark.asyncio
async def test_home_and_result_pages_are_served() -> None:
    home = await request("GET", "/")
    result = await request("GET", "/result")

    assert home.status_code == 200
    assert result.status_code == 200
    assert home.headers["cache-control"] == "no-store, max-age=0"
    assert "<title>TripGraph</title>" in home.text
    assert "开始规划我的旅行" in home.text
    assert 'id="resultView"' in home.text
    assert 'id="sideNav"' in home.text
    assert 'id="daysAccordion"' in home.text
    assert 'id="daySelector"' not in home.text
    assert 'id="tracePanel"' not in home.text
    assert 'id="mapCanvas"' in home.text
    assert "webapi.amap.com/loader.js" in home.text


@pytest.mark.asyncio
async def test_demo_plan_has_the_reference_response_shape() -> None:
    response = await request(
        "POST",
        "/api/trip/plan",
        json={
            "city": "杭州",
            "start_date": "2026-08-01",
            "end_date": "2026-08-03",
            "travel_days": 3,
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
            "preferences": ["历史文化", "美食"],
            "free_text_input": "行程不要过满",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"success", "message", "data"}
    assert payload["success"] is True
    assert set(payload["data"]) == {
        "city",
        "start_date",
        "end_date",
        "days",
        "weather_info",
        "overall_suggestions",
        "budget",
    }
    assert len(payload["data"]["days"]) == 3
    assert all(len(day["attractions"]) == 2 for day in payload["data"]["days"])
    assert [day["day_index"] for day in payload["data"]["days"]] == [0, 1, 2]
    assert set(payload["data"]["budget"]) == {
        "total_attractions",
        "total_hotels",
        "total_meals",
        "total_transportation",
        "total",
    }


@pytest.mark.asyncio
async def test_removed_compatibility_and_graph_endpoints_are_not_exposed() -> None:
    old_plan = await request("POST", "/api/trips/plan", json={})
    graph = await request("GET", "/api/graph")

    assert old_plan.status_code == 404
    assert graph.status_code == 404


@pytest.mark.asyncio
async def test_api_rejects_reversed_dates() -> None:
    response = await request(
        "POST",
        "/api/trip/plan",
        json={
            "city": "杭州",
            "start_date": "2026-08-03",
            "end_date": "2026-08-01",
            "travel_days": 1,
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_map_config_exposes_only_browser_js_credentials() -> None:
    response = await request("GET", "/api/maps/config")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "server-only-mcp-key" not in response.text
    assert response.json() == {
        "enabled": True,
        "key": "test-js-key",
        "security_code": "test-security-code",
    }


@pytest.mark.asyncio
async def test_photo_endpoint_falls_back_without_exposing_credentials() -> None:
    response = await request("GET", "/api/poi/photo", params={"name": "西湖"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["name"] == "西湖"
    assert "photo_url" in response.json()["data"]
    assert "server-only-mcp-key" not in response.text


@pytest.mark.asyncio
async def test_export_dependencies_are_served_locally() -> None:
    html2canvas = await request("GET", "/static/vendor/html2canvas.min.js")
    jspdf = await request("GET", "/static/vendor/jspdf.umd.min.js")

    assert html2canvas.status_code == 200
    assert jspdf.status_code == 200
    assert len(html2canvas.content) > 100_000
    assert len(jspdf.content) > 100_000


@pytest.mark.asyncio
async def test_frontend_matches_reference_accordion_and_polyline_map() -> None:
    response = await request("GET", "/static/app.js")

    assert response.status_code == 200
    assert "function toggleDay(index)" in response.text
    toggle_day_source = response.text.split("function toggleDay(index)", 1)[1].split(
        "function renderDay", 1
    )[0]
    map_source = response.text.split("async function initMap()", 1)[1].split(
        "function createMarker", 1
    )[0]
    assert "initMap()" in toggle_day_source
    assert "currentPlan.days[activeDayIndex]" in map_source
    assert "currentPlan.days.forEach" not in map_source
    assert 'class="collapse-item ' in response.text
    assert "'AMap.Marker'" in response.text
    assert "'AMap.Polyline'" in response.text
    assert "'AMap.InfoWindow'" in response.text
    assert "new AMap.Polyline" in response.text
    assert "AMap.Walking" not in response.text
    assert "AMap.Driving" not in response.text
    assert "AMap.Transfer" not in response.text
    assert "routeSummary" not in response.text
    assert "trace" not in response.text.lower()
    assert "function toggleEditMode()" in response.text
    assert "function saveChanges()" in response.text
    assert "function cancelEdit()" in response.text
    assert "function moveAttraction(" in response.text
    assert "function deleteAttraction(" in response.text
    assert "async function exportAsImage()" in response.text
    assert "async function exportAsPDF()" in response.text
    assert "function getAttractionImage(" in response.text
    assert "/api/poi/photo?name=" in response.text
