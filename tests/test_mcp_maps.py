from __future__ import annotations

from typing import Any

import pytest

from app.services.mcp_maps import AmapMCPService, MCPServiceError


class FakeTool:
    def __init__(self, name: str, result: Any) -> None:
        self.name = name
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, arguments: dict[str, Any]) -> Any:
        self.calls.append(arguments)
        return self.result


class FlakyTool(FakeTool):
    def __init__(self, name: str, result: Any) -> None:
        super().__init__(name, result)
        self.attempts = 0

    async def ainvoke(self, arguments: dict[str, Any]) -> Any:
        self.attempts += 1
        if self.attempts == 1:
            raise ConnectionError("temporary failure")
        return await super().ainvoke(arguments)


class FakeClient:
    def __init__(self, tools: list[FakeTool] | None = None, error: Exception | None = None) -> None:
        self.tools = tools or []
        self.error = error
        self.load_count = 0

    async def get_tools(self) -> list[FakeTool]:
        self.load_count += 1
        if self.error:
            raise self.error
        return self.tools


@pytest.mark.asyncio
async def test_mcp_service_discovers_tools_once_and_invokes_text_search() -> None:
    tool = FakeTool("maps_text_search", '{"pois":[{"name":"西湖"}]}')
    client = FakeClient([tool])
    captured: dict[str, Any] = {}

    def client_factory(connections: dict[str, Any], **kwargs: Any) -> FakeClient:
        captured.update(connections)
        assert kwargs["handle_tool_errors"] is False
        return client

    service = AmapMCPService(
        api_key="key+with/slash",
        mcp_url="https://mcp.amap.com/mcp",
        client_factory=client_factory,
    )

    first = await service.search_pois(city="杭州", keywords="历史文化")
    second = await service.search_pois(city="杭州", keywords="酒店")

    assert "西湖" in first
    assert "西湖" in second
    assert client.load_count == 1
    assert tool.calls == [
        {"keywords": "历史文化", "city": "杭州", "citylimit": True},
        {"keywords": "酒店", "city": "杭州", "citylimit": True},
    ]
    assert captured["amap"]["transport"] == "http"
    assert captured["amap"]["url"] == "https://mcp.amap.com/mcp?key=key%2Bwith%2Fslash"


@pytest.mark.asyncio
async def test_mcp_service_fetches_poi_details_by_id() -> None:
    tool = FakeTool(
        "maps_search_detail",
        '{"id":"B001","location":"120.131487,30.196338"}',
    )
    service = AmapMCPService(
        api_key="secret",
        client_factory=lambda *_args, **_kwargs: FakeClient([tool]),
    )

    result = await service.get_poi_details(["B001"])

    assert result == ['{"id":"B001","location":"120.131487,30.196338"}']
    assert tool.calls == [{"id": "B001"}]


@pytest.mark.asyncio
async def test_mcp_service_retries_one_transient_tool_failure() -> None:
    tool = FlakyTool("maps_weather", '{"forecasts":[{"city":"杭州"}]}')
    service = AmapMCPService(
        api_key="secret",
        client_factory=lambda *_args, **_kwargs: FakeClient([tool]),
    )

    result = await service.get_weather("杭州")

    assert "杭州" in result
    assert tool.attempts == 2


@pytest.mark.asyncio
async def test_mcp_service_extracts_text_content_blocks() -> None:
    tool = FakeTool(
        "maps_weather",
        [{"type": "text", "text": '{"forecasts":[{"city":"杭州"}]}'}],
    )
    service = AmapMCPService(
        api_key="secret",
        client_factory=lambda *_args, **_kwargs: FakeClient([tool]),
    )

    result = await service.get_weather("杭州")

    assert result == '{"forecasts":[{"city":"杭州"}]}'
    assert tool.calls == [{"city": "杭州"}]


@pytest.mark.asyncio
async def test_mcp_service_hides_credentials_when_connection_fails() -> None:
    secret = "do-not-leak"
    client = FakeClient(error=RuntimeError(f"failed: https://mcp.amap.com/mcp?key={secret}"))
    service = AmapMCPService(
        api_key=secret,
        client_factory=lambda *_args, **_kwargs: client,
    )

    with pytest.raises(MCPServiceError) as exc_info:
        await service.get_weather("杭州")

    assert secret not in str(exc_info.value)
    assert "高德 MCP 服务" in str(exc_info.value)
