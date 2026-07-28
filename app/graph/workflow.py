from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.graph.agents import AgentSuite
from app.graph.state import TravelState
from app.models import ResearchBundle


def build_travel_graph(agents: AgentSuite):
    """构建与参考项目职责一致的四 Agent LangGraph。"""

    async def attractions(state: TravelState) -> dict:
        return {"attractions": await agents.research_attractions(state["request"])}

    async def weather(state: TravelState) -> dict:
        return {"weather": await agents.research_weather(state["request"])}

    async def hotels(state: TravelState) -> dict:
        return {"hotels": await agents.research_hotels(state["request"])}

    async def planner(state: TravelState) -> dict:
        research = ResearchBundle(
            attractions=state.get("attractions", []),
            weather=state.get("weather", []),
            hotels=state.get("hotels", []),
        )
        return {"plan": await agents.draft(state["request"], research)}

    builder = StateGraph(TravelState)
    builder.add_node("attractions", attractions)
    builder.add_node("weather", weather)
    builder.add_node("hotels", hotels)
    builder.add_node("planner", planner)

    # 与参考项目保持相同调用顺序，同时避免高德 MCP 在短时间内建立多条连接。
    builder.add_edge(START, "attractions")
    builder.add_edge("attractions", "weather")
    builder.add_edge("weather", "hotels")
    builder.add_edge("hotels", "planner")
    builder.add_edge("planner", END)
    return builder.compile()
