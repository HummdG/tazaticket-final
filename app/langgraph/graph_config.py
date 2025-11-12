"""
LangGraph configuration and setup for the flight search chatbot
"""

import os
import json, ast
import asyncio
from typing import Annotated
from typing_extensions import TypedDict
from dotenv import load_dotenv

from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import ToolMessage, HumanMessage, AIMessage

from app.tools.FlightSearchStateMachine import FlightSearchStateMachine, BulkFlightSearch
from app.tools.SearchResultTool import SearchResultManager, StoreSearchResult
from app.tools.TravelportReservation import (
    TravelportAuthentication,
    TravelportFlightSearch,
    # TravelportInitiateReservationWorkbench,
    # TravelportAddOfferToReservation,
    # TravelportAddTravelerToReservation,
    # TravelportCommitReservation,
    # TravelportFullReservation  # Commented out as per instructions
)
from app.tools.UnifiedTravelportBooking import unified_travelport_booking

from app.langgraph.memory_manager import memory_manager
from app.langgraph.prompt import PROMPT as system_prompt 
from app.services.TravelportDataAdapter import TravelportDataAdapter

# Global variable to store current thread_id for tools
_current_thread_id = "default"

def get_current_thread_id():
    """Get the current thread_id for use in tools"""
    return _current_thread_id


class State(TypedDict):
    """State definition for the LangGraph conversation flow"""
    messages: Annotated[list[dict], add_messages]


class BasicToolNode:
    """Node that runs the tools requested in the last AI message."""

    def __init__(self, tools: list) -> None:
        self.tools_by_name = {tool.name: tool for tool in tools}

    async def __call__(self, inputs: dict):
        # Extract thread_id and wa_id from config for tracing
        # --- FIX: Properly extract and inject wa_id + thread_id ---
        # configurable = inputs.get("configurable") or {}
        # thread_id = configurable.get("thread_id") or configurable.get("wa_id") or "unknown"
        # wa_id = configurable.get("wa_id") or thread_id

        # --- FIX: Ensure valid thread_id + wa_id are always available ---
        configurable = inputs.get("configurable") or {}
        global _current_thread_id
        
        thread_id = configurable.get("thread_id") or _current_thread_id
        wa_id = configurable.get("wa_id") or thread_id  # use thread_id as fallback for wa_id
        
        # Defensive fallback: never allow 'unknown'
        if thread_id in ("unknown", None, ""):
            thread_id = _current_thread_id or "default"
        if wa_id in ("unknown", None, ""):
            wa_id = thread_id
        
        print(f"[BasicToolNode] ✅ Propagated IDs → thread_id={thread_id}, wa_id={wa_id}")
        
        
        if messages := inputs.get("messages", []):
            message = messages[-1]
        else:
            raise ValueError("No messages in inputs")
        
        outputs = []
        for tool_call in message.tool_calls:
            # Add detailed tracing for tool calls
            print(f"[LangGraph-Trace] 🛠️  TOOL CALL: '{tool_call['name']}' | Thread: {thread_id} | ID: {tool_call['id']}")
            print(f"[LangGraph-Trace]    Args: {tool_call['args']}")
            
            # Store original args to preserve any existing values
            tool_args = tool_call["args"].copy()  # Make a copy to avoid modifying original
            
            # Inject IDs into every tool call automatically
            tool_args["thread_id"] = thread_id
            tool_args["wa_id"] = wa_id

            print(f"[BasicToolNode] 🧩 Using wa_id={wa_id}, thread_id={thread_id}")
            
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
            
            # Use async invocation for StructuredTool instances
            tool = self.tools_by_name[tool_call["name"]]
            if hasattr(tool, 'ainvoke'):
                # This is a StructuredTool that only supports async invocation
                print(f"[BasicToolNode] Invoking tool '{tool_call['name']}' asynchronously with args: {tool_args}")
                tool_result = await tool.ainvoke(tool_args)
            else:
                # Fall back to sync invocation for other tool types
                print(f"[BasicToolNode] Invoking tool '{tool_call['name']}' synchronously with args: {tool_args}")
                tool_result = tool.invoke(tool_args)
            
            print(f"[LangGraph-Trace] 📤 TOOL RESULT: '{tool_call['name']}' | Thread: {thread_id} | Success: {tool_result is not None}")
            print(f"[LangGraph-Trace]    Result preview: {str(tool_result)[:200]}{'...' if len(str(tool_result)) > 200 else ''}")
            
            # --- FIX: prevent infinite loops from repeating failed bookings ---
            if isinstance(tool_result, dict) and tool_result.get("stop_graph"):
                print(f"[GraphConfig] ⛔ Stop marker received, terminating graph for thread {thread_id}")
                return {"messages": [
                    ToolMessage(
                        content=str(tool_result),
                        name=tool_call["name"],
                        tool_call_id=tool_call["id"],
                    )
                ]}
            
            outputs.append(
                ToolMessage(
                    content=str(tool_result),
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                )
            )
        return {"messages": outputs}


async def chatbot(state: State, llm_with_tools):
    """Main chatbot node that processes user messages"""
    # Extract thread_id for tracing
    thread_id = "unknown"
    if state.get("messages"):
        # Look for thread_id in the last message's metadata
        last_msg = state["messages"][-1]
        if hasattr(last_msg, 'additional_kwargs') and 'configurable' in last_msg.additional_kwargs:
            thread_id = last_msg.additional_kwargs['configurable'].get('thread_id', 'unknown')
    
    print(f"[LangGraph-Trace] 🤖 CHATBOT: Processing messages | Thread: {thread_id} | Message count: {len(state['messages'])}")
    
    # Get the last human message for context
    human_messages = [msg for msg in state["messages"] if hasattr(msg, 'type') and msg.type == 'human']
    if human_messages:
        last_user_message = human_messages[-1]
        user_content = getattr(last_user_message, 'content', 'No content')[:100]  # First 100 chars
        print(f"[LangGraph-Trace]    Last user input: '{user_content}...'")
    
    response = await llm_with_tools.ainvoke(state["messages"])
    
    # Check if the response contains tool calls
    has_tool_calls = hasattr(response, 'tool_calls') and response.tool_calls
    print(f"[LangGraph-Trace]    LLM Response | Has Tool Calls: {has_tool_calls}")
    if has_tool_calls:
        print(f"[LangGraph-Trace]    Tool Calls: {[call['name'] for call in response.tool_calls]}")
    
    return {"messages": [response]}


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
    
    # Extract thread_id for tracing from the messages if available
    thread_id = "unknown"
    if hasattr(ai_message, 'additional_kwargs') and 'configurable' in ai_message.additional_kwargs:
        thread_id = ai_message.additional_kwargs['configurable'].get('thread_id', 'unknown')
    elif isinstance(state, dict) and 'messages' in state and state['messages']:
        # Look for thread_id in the state configuration
        # This requires checking the invoke configuration which may not be directly available here
        pass
    
    # Log the decision being made
    has_tool_calls = hasattr(ai_message, "tool_calls") and len(ai_message.tool_calls) > 0
    print(f"[LangGraph-Trace] 💡 DECISION: Route Tools | Thread: {thread_id} | Has Tool Calls: {has_tool_calls}")
    
    if has_tool_calls:
        print(f"[LangGraph-Trace]    Tool Calls: {[call['name'] for call in ai_message.tool_calls]}")
        return "tools"
    
    print(f"[LangGraph-Trace]    No tool calls found, routing to END")
    return END


def create_graph():
    """
    Create and configure the LangGraph conversation flow
    """
    print("[LangGraph-Trace] 🏗️  GRAPH CREATION: Initializing LangGraph")
    
    # Load environment variables
    load_dotenv()
    
    # Get OpenAI API key
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    
    # Initialize tools
    tools = [
        FlightSearchStateMachine, 
        BulkFlightSearch, 
        SearchResultManager, 
        StoreSearchResult,
        TravelportAuthentication,
        TravelportFlightSearch,
        # TravelportInitiateReservationWorkbench,
        # TravelportAddOfferToReservation,
        # TravelportAddTravelerToReservation,
        # TravelportCommitReservation,
        # TravelportFullReservation,
        unified_travelport_booking,
    ]
    
    print(f"[LangGraph-Trace]    Tools registered: {[tool.name for tool in tools]}")
    
    # Initialize LLM
    llm = init_chat_model("gpt-4o-mini", model_provider="openai", temperature=0)
    llm_with_tools = llm.bind_tools(tools)
    
    print("[LangGraph-Trace]    LLM initialized and tools bound")
    
    # Create state graph
    graph_builder = StateGraph(State)
    
    # Create chatbot node with bound LLM
    async def chatbot_node(state: State):
        return await chatbot(state, llm_with_tools)
    
    # Add nodes
    print("[LangGraph-Trace]    Adding nodes to graph")
    graph_builder.add_node("chatbot", chatbot_node)
    
    tool_node = BasicToolNode(tools=tools)
    async def tool_node_wrapper(state):
        return await tool_node(state)
    graph_builder.add_node("tools", tool_node_wrapper)
    
    

    
    # Add edges
    print("[LangGraph-Trace]    Adding edges to graph")
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
    print("[LangGraph-Trace]    Compiling graph with memory checkpointer")
    graph = graph_builder.compile(checkpointer=memory)
    
    print("[LangGraph-Trace] ✅ GRAPH CREATED: LangGraph compiled with InMemorySaver checkpointer")
    
    return graph


async def invoke_graph(graph, user_message: str, thread_id: str = "default", is_voice: bool = False, detected_language: str = "en"):
    """
    Async function to invoke the graph with a user message.
    Integrates with MemoryManager for persistent chat history.
    """
    global _current_thread_id
    _current_thread_id = thread_id
    print(f"[LangGraph-Trace] ▶️  GRAPH INVOCATION: Starting | Thread: {thread_id} | Voice: {is_voice} | Lang: {detected_language}")
    print(f"[LangGraph-Trace]    User message: '{user_message[:100]}{'...' if len(user_message) > 100 else ''}'")
    print(f"[GraphConfig] Set global thread_id to: {_current_thread_id}")
    
    # Initialize session and load context from DynamoDB
    print(f"[LangGraph-Trace] 🔄 SESSION: Starting session for thread {thread_id}")
    await memory_manager.on_session_start(thread_id)
    
    # Add user message to memory manager (starts new pair)
    print(f"[LangGraph-Trace] 📥 USER MESSAGE: Adding to memory | Thread: {thread_id}")
    await memory_manager.add_user_message(thread_id, user_message)
    
    try:
        # Get context for LLM (flattened pairs)
        print(f"[LangGraph-Trace] 📚 CONTEXT: Retrieving context for LLM | Thread: {thread_id}")
        context_messages = await memory_manager.get_context_for_llm(thread_id)
        print(f"[GraphConfig] Using {len(context_messages)} context messages for LLM")
        
        # Add Travelport system context knowledge
        from langchain_core.messages import SystemMessage

        # Use the imported system prompt from .prompt
        processed_system_prompt = system_prompt.strip()
        processed_system_prompt = SystemMessage(content=processed_system_prompt)

        # Convert context to LangChain messages for the graph
        langchain_messages = [processed_system_prompt]  # Start with system prompt
        for msg in context_messages:
            if msg["role"] == "user":
                langchain_messages.append(HumanMessage(content=msg["content"]))
            else:  # assistant
                langchain_messages.append(AIMessage(content=msg["content"]))
        
        print(f"[GraphConfig] Converted to {len(langchain_messages)} LangChain messages")
        print(f"[LangGraph-Trace] 📝 MESSAGES: Prepared {len(langchain_messages)} messages for LLM")
        
        # --- FIX: propagate wa_id consistently ---
        config = {
            "configurable": {
                "thread_id": thread_id,
                "wa_id": thread_id,  # ensure WhatsApp ID is passed downstream
                "is_voice_mode": is_voice,
                "detected_language": detected_language,
            }
        }
        
        print(f"[GraphConfig] Creating config with thread_id: {thread_id}")
        print(f"[GraphConfig] Full config: {config}")
        
        # Invoke the graph with the full context
        # Set a reasonable recursion limit to prevent infinite loops while allowing multiple tool calls
        config["recursion_limit"] = 50  # Increased to allow for multiple tool calls in sequence
        print(f"[LangGraph-Trace] 🚀 EXECUTION: Invoking graph | Recursion limit: {config['recursion_limit']}")
        
        state = await graph.ainvoke(
            {"messages": langchain_messages},
            config,
        )
        
        print(f"[LangGraph-Trace] ✅ EXECUTION: Graph invocation completed | Thread: {thread_id}")
        
        # Extract assistant response and add to memory manager (closes pair)
        assistant_text = extract_last_ai_text(state)
        if assistant_text:
            print(f"[LangGraph-Trace] 📤 RESPONSE: Processing assistant response | Length: {len(assistant_text)} chars")
            print(f"[GraphConfig] Adding assistant response to memory: '{assistant_text[:50]}...'")
            print(f"[GraphConfig] About to add assistant message for thread {thread_id}")
            await memory_manager.add_assistant_message(thread_id, assistant_text)
            print(f"[GraphConfig] Successfully added assistant response to memory for thread {thread_id}")
            print(f"[LangGraph-Trace] 💾 MEMORY: Response stored in memory | Thread: {thread_id}")
        else:
            print("[GraphConfig] Warning: No assistant response extracted from state")
            print(f"[LangGraph-Trace] ⚠️  RESPONSE: No assistant text extracted from state")
            
        print(f"[LangGraph-Trace] 📋 COMPLETION: Graph invocation completed successfully | Thread: {thread_id}")
        return state
    except Exception as e:
        print(f"[LangGraph-Trace] ❌ ERROR: Exception during graph invocation | Thread: {thread_id} | Error: {e}")
        print(f"[GraphConfig] Error during graph invocation: {e}")
        import traceback
        traceback.print_exc()
        
        # Ensure we clean up the open pair if there was an error
        # This prevents the "No open pair to close" error on subsequent calls
        print(f"[GraphConfig] Attempting to recover from error by closing open pair for thread {thread_id}")
        try:
            # Try to add a generic error message as the assistant response to close the pair
            error_response = "Sorry, there was an error processing your request. Please try again."
            await memory_manager.add_assistant_message(thread_id, error_response)
            print(f"[GraphConfig] Successfully recovered by adding error response for thread {thread_id}")
            print(f"[LangGraph-Trace] 💾 MEMORY: Error recovery response stored | Thread: {thread_id}")
        except ValueError as ve:
            # If there's no open pair, this is expected and we can ignore it
            if "No open pair to close" in str(ve):
                print(f"[GraphConfig] Expected: No open pair to close for thread {thread_id} - likely the error occurred before add_user_message")
            else:
                print(f"[GraphConfig] Unexpected error closing pair for thread {thread_id}: {ve}")
        except Exception as close_error:
            print(f"[GraphConfig] Unexpected error when trying to close pair for thread {thread_id}: {close_error}")
        
        # Re-raise the original exception to maintain proper error handling
        raise


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

