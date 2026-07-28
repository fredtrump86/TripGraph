from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class MCPServiceError(RuntimeError):
    """高德 MCP 服务不可用或返回了无效结果。"""


def _authenticated_url(url: str, api_key: str) -> str:
    parts = urlsplit(url)
    query = [(name, value) for name, value in parse_qsl(parts.query) if name.lower() != "key"]
    query.append(("key", api_key))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (_result_text(item) for item in value)))
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if "structured_content" in value:
            return json.dumps(value["structured_content"], ensure_ascii=False)
        if "content" in value:
            return _result_text(value["content"])
        return json.dumps(value, ensure_ascii=False)

    artifact = getattr(value, "artifact", None)
    if isinstance(artifact, dict) and artifact.get("structured_content") is not None:
        return json.dumps(artifact["structured_content"], ensure_ascii=False)
    content = getattr(value, "content", None)
    if content is not None:
        return _result_text(content)
    return str(value)


class AmapMCPService:
    """通过 LangChain MCP 客户端调用高德官方 MCP Server。"""

    def __init__(
        self,
        api_key: str,
        mcp_url: str = "https://mcp.amap.com/mcp",
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        if client_factory is None:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            client_factory = MultiServerMCPClient

        connections = {
            "amap": {
                "transport": "http",
                "url": _authenticated_url(mcp_url, api_key),
            }
        }
        self._client = client_factory(connections, handle_tool_errors=False)
        self._tools: dict[str, Any] | None = None
        self._load_lock = asyncio.Lock()

    async def search_pois(self, city: str, keywords: str) -> str:
        return await self._call_tool(
            "maps_text_search",
            {"keywords": keywords, "city": city, "citylimit": True},
        )

    async def get_poi_details(self, poi_ids: list[str]) -> list[str]:
        """根据文本搜索返回的 POI ID 补齐坐标等详情。"""

        semaphore = asyncio.Semaphore(2)

        async def fetch(poi_id: str) -> str:
            async with semaphore:
                return await self._call_tool("maps_search_detail", {"id": poi_id})

        unique_ids = list(dict.fromkeys(poi_id for poi_id in poi_ids if poi_id))
        return list(await asyncio.gather(*(fetch(poi_id) for poi_id in unique_ids)))

    async def get_weather(self, city: str) -> str:
        return await self._call_tool("maps_weather", {"city": city})

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                tools = await self._get_tools()
                tool = tools.get(name)
                if tool is None:
                    raise MCPServiceError(f"高德 MCP Server 未提供必需工具：{name}")
                result = _result_text(await tool.ainvoke(arguments)).strip()
                if not result:
                    raise MCPServiceError(f"高德 MCP 工具 {name} 返回了空结果")
                return result
            except MCPServiceError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(0.2)

        raise MCPServiceError(
            "高德 MCP 服务连接或调用失败，请检查网络和 AMAP_API_KEY。"
        ) from last_error

    async def _get_tools(self) -> dict[str, Any]:
        if self._tools is not None:
            return self._tools
        async with self._load_lock:
            if self._tools is None:
                tools = await self._client.get_tools()
                self._tools = {tool.name: tool for tool in tools}
        return self._tools
