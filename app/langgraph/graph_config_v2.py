"""
LangGraph v2 Configuration
Simplified deterministic graph connecting FSM → SearchResultManager → Booking
"""

import os, asyncio
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain.chat_models import init_chat_model
from langchain_core.messages import ToolMessage

from app.tools.FlightSearchFSM_v2 import FlightSearchFSM_v2
from app.services.search_result_manager_v2 import search_result_manager
from app.tools.UnifiedTravelportBooking_v2 import UnifiedTravelportBooking_v2

# ------------------------------------------------
# Define Graph State
# ------------------------------------------------
class State(TypedDict):
    messages: list

# ------------------------------------------------
# Tool Router
# ------------------------------------------------
class BasicToolNode:
    def __init__(self, tools: list):
        self.tools = {tool.name: tool for tool in tools}

    async def __call__(self, inputs: dict):
        message = inputs["messages"][-1]
        outputs = []
        for call in message.tool_calls:
            name, args = call["name"], call["args"]
            tool = self.tools[name]
            print(f"[Graph] Running tool: {name}")
            result = await tool.ainvoke(args)
            outputs.append(
                ToolMessage(content=str(result), name=name, tool_call_id=call["id"])
            )
        return {"messages": outputs}

# ------------------------------------------------
# Chatbot Node
# ------------------------------------------------
async def chatbot(state: State, llm):
    """Handles user messages"""
    response = await llm.ainvoke(state["messages"])
    return {"messages": [response]}

# ------------------------------------------------
# Graph Builder
# ------------------------------------------------
def create_graph():
    tools = [FlightSearchFSM_v2, UnifiedTravelportBooking_v2]
    llm = init_chat_model("gpt-4o-mini", model_provider="openai", temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    builder = StateGraph(State)

    async def chatbot_node(state: State):
        return await chatbot(state, llm_with_tools)

    tool_node = BasicToolNode(tools=tools)

    builder.add_node("chatbot", chatbot_node)
    builder.add_node("tools", tool_node)

    builder.add_conditional_edges(
        "chatbot",
        lambda s: "tools" if hasattr(s["messages"][-1], "tool_calls") else END,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "chatbot")
    builder.add_edge(START, "chatbot")

    print("[Graph] ✅ LangGraph v2 ready.")
    return builder.compile()