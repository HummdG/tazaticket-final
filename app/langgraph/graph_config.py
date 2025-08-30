"""
LangGraph configuration and setup for the flight search chatbot
"""

import os
import json, ast
from typing import Annotated
from typing_extensions import TypedDict
from dotenv import load_dotenv

from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import ToolMessage, HumanMessage, AIMessage

from ..tools.FlightSearchStateMachine import FlightSearchStateMachine, BulkFlightSearch
from .memory_manager import memory_manager


class State(TypedDict):
    """State definition for the LangGraph conversation flow"""
    messages: Annotated[list[dict], add_messages]


class BasicToolNode:
    """Node that runs the tools requested in the last AI message."""

    def __init__(self, tools: list) -> None:
        self.tools_by_name = {tool.name: tool for tool in tools}

    def __call__(self, inputs: dict):
        if messages := inputs.get("messages", []):
            message = messages[-1]
        else:
            raise ValueError("No messages in inputs")
        
        outputs = []
        for tool_call in message.tool_calls:
            # Pass thread_id, user_input_text, and voice mode to tools that need them
            tool_args = tool_call["args"]
            if tool_call["name"] in ["FlightSearchStateMachine", "BulkFlightSearch"]:
                # Always override thread_id to ensure correct value from config
                extracted_thread_id = inputs.get("configurable", {}).get("thread_id", "default")
                existing_thread_id = tool_args.get("thread_id", "not_set")
                tool_args["thread_id"] = extracted_thread_id
                print(f"[BasicToolNode] Setting thread_id for {tool_call['name']}: {extracted_thread_id} (was: {existing_thread_id})")
                print(f"[BasicToolNode] Configurable context: {inputs.get('configurable', {})}")
                
                # Set mode of conversation based on voice detection
                is_voice_mode = inputs.get("configurable", {}).get("is_voice_mode", False)
                if "mode_of_conversation" not in tool_args:
                    tool_args["mode_of_conversation"] = "voice" if is_voice_mode else "text"
                    print(f"[BasicToolNode] Setting mode_of_conversation: {tool_args['mode_of_conversation']}")
                
                # Set detected language
                detected_language = inputs.get("configurable", {}).get("detected_language", "en")
                if "detected_language" not in tool_args:
                    tool_args["detected_language"] = detected_language
                    print(f"[BasicToolNode] Setting detected_language: {detected_language}")
                
                if tool_call["name"] in ["FlightSearchStateMachine", "BulkFlightSearch"]:
                    if "user_input_text" not in tool_args or not tool_args["user_input_text"]:
                        # Find the original user message for carrier parsing
                        user_messages = [msg for msg in inputs.get("messages", []) if hasattr(msg, "type") and msg.type == "human"]
                        if user_messages:
                            tool_args["user_input_text"] = user_messages[-1].content
            
            tool_result = self.tools_by_name[tool_call["name"]].invoke(tool_args)
            outputs.append(
                ToolMessage(
                    content=str(tool_result),
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                )
            )
        return {"messages": outputs}


def chatbot(state: State, llm_with_tools):
    """Main chatbot node that processes user messages"""
    return {"messages": [llm_with_tools.invoke(state["messages"])]}


def route_tools(state: State):
    """
    Use in the conditional_edge to route to the ToolNode if the last message
    has tool calls. Otherwise, route to the end.
    """
    if isinstance(state, list):
        ai_message = state[-1]
    elif messages := state.get("messages", []):
        ai_message = messages[-1]
    else:
        raise ValueError("No messages in state", {state})
    if hasattr(ai_message, "tool_calls") and len(ai_message.tool_calls) > 0:
        return "tools"
    
    return END


def create_graph():
    """
    Create and configure the LangGraph conversation flow
    """
    # Load environment variables
    load_dotenv()
    
    # Get OpenAI API key
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    
    # Initialize tools
    tools = [FlightSearchStateMachine, BulkFlightSearch]
    
    # Initialize LLM
    llm = init_chat_model("gpt-4o-mini", model_provider="openai", temperature=0)
    llm_with_tools = llm.bind_tools(tools)
    
    # Create state graph
    graph_builder = StateGraph(State)
    
    # Create chatbot node with bound LLM
    def chatbot_node(state: State):
        return chatbot(state, llm_with_tools)
    
    # Add nodes
    graph_builder.add_node("chatbot", chatbot_node)
    
    # Create and add tool node
    tool_node = BasicToolNode(tools=tools)
    graph_builder.add_node("tools", tool_node)
    
    # Add edges
    graph_builder.add_conditional_edges(
        "chatbot",
        route_tools,
        {"tools": "tools", END: END},
    )
    
    # Any time a tool is called, we return to the chatbot to decide the next step
    graph_builder.add_edge("tools", "chatbot")
    graph_builder.add_edge(START, "chatbot")
    
    # Add memory checkpoint (InMemorySaver for LangGraph checkpointing)
    memory = InMemorySaver()
    graph = graph_builder.compile(checkpointer=memory)
    
    print("[GraphConfig] LangGraph created with InMemorySaver checkpointer")
    
    return graph


def invoke_graph(graph, user_message: str, thread_id: str = "default", is_voice: bool = False, detected_language: str = "en"):
    """
    Convenience function to invoke the graph with a user message.
    Integrates with MemoryManager for persistent chat history.
    """
    print(f"[GraphConfig] Invoking graph for thread {thread_id} with message: '{user_message[:50]}...' (voice: {is_voice}, language: {detected_language})")
    
    # Initialize session and load context from DynamoDB
    memory_manager.on_session_start(thread_id)
    
    # Add user message to memory manager (starts new pair)
    memory_manager.add_user_message(thread_id, user_message)
    
    # Get context for LLM (flattened pairs)
    context_messages = memory_manager.get_context_for_llm(thread_id)
    print(f"[GraphConfig] Using {len(context_messages)} context messages for LLM")
    
    # Convert context to LangChain messages for the graph
    langchain_messages = []
    for msg in context_messages:
        if msg["role"] == "user":
            langchain_messages.append(HumanMessage(content=msg["content"]))
        else:  # assistant
            langchain_messages.append(AIMessage(content=msg["content"]))
    
    print(f"[GraphConfig] Converted to {len(langchain_messages)} LangChain messages")
    
    # Create configuration with voice mode and language information
    config = {
        "configurable": {
            "thread_id": thread_id,
            "is_voice_mode": is_voice,
            "detected_language": detected_language
        }
    }
    
    # Invoke the graph with the full context
    state = graph.invoke(
        {"messages": langchain_messages},
        config,
    )
    
    # Extract assistant response and add to memory manager (closes pair)
    assistant_text = extract_last_ai_text(state)
    if assistant_text:
        print(f"[GraphConfig] Adding assistant response to memory: '{assistant_text[:50]}...'")
        memory_manager.add_assistant_message(thread_id, assistant_text)
    else:
        print("[GraphConfig] Warning: No assistant response extracted from state")
    
    return state


def extract_last_ai_text(state: dict) -> str:
    """
    Extract the last AI message content from the graph state
    """
    messages = state.get("messages", []) if isinstance(state, dict) else []
    if not messages:
        return ""
    last = messages[-1]
    content = getattr(last, "content", None)
    if content is None:
        return str(last)
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                parts.append(part.get("text") or "")
            else:
                parts.append(str(part))
        return "\n".join([p for p in parts if p])
    return content if isinstance(content, str) else str(content)

