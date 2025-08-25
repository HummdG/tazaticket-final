import os 
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta
import json
from langchain_core.tools import tool
from langchain_core.tools import tool as lc_tool
from langchain.chat_models import init_chat_model

from typing import Annotated

from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from langgraph.checkpoint.memory import InMemorySaver

from fastapi import FastAPI, Form
from fastapi.responses import Response
import html

# Import our modules
from app.statemachine.ConversationFlowSM import ConversationFlowSM
from app.payloads.OneWayFlightSearch import OneWayFlightSearch
from app.payloads.RoundTripFlightSearch import RoundTripFlightSearch
from app.tools.TravelportSearch import TravelportSearch

load_dotenv()

# Import airline codes and carrier functions
from app.airline_codes import (
    AIRLINE_CODES, 
    DEFAULT_PREFERRED_CARRIERS, 
    get_airline_name, 
    parse_carrier_preference,
    get_all_carrier_codes,
    get_carriers_by_region
)

# State machine storage per thread
state_machines = {}

def get_or_create_state_machine(thread_id: str) -> ConversationFlowSM:
    """Get existing state machine or create new one for thread"""
    if thread_id not in state_machines:
        state_machines[thread_id] = ConversationFlowSM()
    return state_machines[thread_id]

@tool("FlightSearchStateMachine")
def FlightSearchStateMachine(origin: str = None, destination: str = None, departure_date: str = None, 
                           return_date: str = None, number_of_passengers: int = 1, 
                           type_of_trip: str = None, user_input_text: str = "", thread_id: str = "default"):
    """
    Manages flight search state and performs search when all required fields are complete.
    Call this tool when user mentions flight/travel plans to update search parameters.
    
    IMPORTANT - Date Guidelines:
    - Always use YYYY-MM-DD format
    - For current year dates like "November 6th" or "6th of November", use current year
    - For past dates in current year, automatically move to next year
    - Never use years before current year (avoid 2023, 2022, etc.)
    - Examples: "November 6th" → "2025-11-06", "next Friday" → calculate future date
    
    For carrier preferences:
    - Pass the full user input text to detect airline preferences
    - If user mentions specific airline (e.g., "Emirates", "Qatar", "EK"), use that carrier
    - Otherwise, use comprehensive default carrier list for broader search results
    """
    import re
    from datetime import datetime, timedelta
    
    def fix_date_year(date_str):
        """Ensure date is in the future - if in past, move to next year"""
        if not date_str:
            return date_str
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            today = datetime.now().date()
            
            # If the date is in the past, move it to next year
            if date_obj < today:
                next_year_date = date_obj.replace(year=today.year + 1)
                return next_year_date.strftime('%Y-%m-%d')
            elif date_obj.year < today.year:
                # If year is definitely wrong (like 2023), use current year
                current_year_date = date_obj.replace(year=today.year)
                if current_year_date < today:
                    next_year_date = date_obj.replace(year=today.year + 1)
                    return next_year_date.strftime('%Y-%m-%d')
                else:
                    return current_year_date.strftime('%Y-%m-%d')
            return date_str
        except:
            return date_str
    
    # Get state machine for this thread
    sm = get_or_create_state_machine(thread_id)
    
    # Parse carrier preference from user input
    preferred_carriers = parse_carrier_preference(user_input_text) if user_input_text else DEFAULT_PREFERRED_CARRIERS
    
    # Update provided fields
    if origin:
        sm.set_variable('origin', origin.upper())
    if destination:
        sm.set_variable('destination', destination.upper())
    if departure_date:
        corrected_departure = fix_date_year(departure_date)
        sm.set_variable('departure_date', corrected_departure)
    if return_date:
        corrected_return = fix_date_year(return_date)
        sm.set_variable('return_date', corrected_return)
    if number_of_passengers:
        sm.set_variable('number_of_passengers', number_of_passengers)
    if type_of_trip:
        # Normalize trip type variations
        normalized_trip_type = type_of_trip.lower().strip()
        if normalized_trip_type in ['oneway', 'one-way', 'one way']:
            normalized_trip_type = 'one-way'
        elif normalized_trip_type in ['roundtrip', 'round-trip', 'round trip', 'return']:
            normalized_trip_type = 'round-trip'
        sm.set_variable('type_of_trip', normalized_trip_type)
    
    # Set defaults if not set
    if not sm.detected_language:
        sm.set_variable('detected_language', 'en')
    if not sm.mode_of_conversation:
        sm.set_variable('mode_of_conversation', 'text')
    
    # Check if complete and perform search
    if sm.get_state() == "complete":
        try:
            if sm.type_of_trip == "one-way":
                payload = OneWayFlightSearch(
                    origin=sm.origin,
                    destination=sm.destination,
                    departure_date=sm.departure_date,
                    number_of_passengers=sm.number_of_passengers,
                    carriers=preferred_carriers
                )
                result = TravelportSearch.invoke({"payload": payload, "trip_type": "one-way"})
            else:
                payload = RoundTripFlightSearch(
                    origin=sm.origin,
                    destination=sm.destination,
                    departure_date=sm.departure_date,
                    return_date=sm.return_date,
                    number_of_passengers=sm.number_of_passengers,
                    carriers=preferred_carriers
                )
                result = TravelportSearch.invoke({"payload": payload, "trip_type": "round-trip"})
            
            if result.get("ok"):
                summary = result.get("summary")
                if summary:
                    # Format detailed flight information
                    if summary.get("price_total"):  # Round-trip
                        price = summary["price_total"]
                        outbound = summary.get("outbound", {})
                        inbound = summary.get("inbound", {})
                        
                        response = f"✈️ Round-trip flight found: {price['total']} {price['currency']}\n\n"
                        
                        if outbound:
                            duration = format_duration(outbound.get("duration_minutes_total"))
                            stops = format_stops(outbound.get("stops_total", 0))
                            response += f"🛫 Outbound: {duration}, {stops}\n"
                            if outbound.get("baggage"):
                                response += f"   Baggage: {format_baggage_summary(outbound['baggage'])}\n"
                        
                        if inbound:
                            duration = format_duration(inbound.get("duration_minutes_total"))
                            stops = format_stops(inbound.get("stops_total", 0))
                            response += f"🛬 Return: {duration}, {stops}\n"
                            if inbound.get("baggage"):
                                response += f"   Baggage: {format_baggage_summary(inbound['baggage'])}\n"
                        
                        # Reset state machine after successful search
                        state_machines[thread_id] = ConversationFlowSM()
                        return response
                    else:  # One-way
                        price = summary.get("price", {})
                        price_text = f"{price.get('total')} {price.get('currency')}" if price.get('total') else "Price not available"
                        
                        duration = format_duration(summary.get("duration_minutes_total"))
                        stops = format_stops(summary.get("stops_total", 0))
                        
                        response = f"✈️ One-way flight found: {price_text}\n"
                        response += f"🛫 Flight: {duration}, {stops}\n"
                        
                        if summary.get("baggage"):
                            response += f"Baggage: {format_baggage_summary(summary['baggage'])}\n"
                        
                        # Reset state machine after successful search
                        state_machines[thread_id] = ConversationFlowSM()
                        return response
                
                # Fallback if no summary
                # Reset state machine after successful search
                state_machines[thread_id] = ConversationFlowSM()
                return f"Flight search completed! Found flights for {sm.origin} to {sm.destination} on {sm.departure_date}."
            else:
                return f"Sorry, I couldn't find flights. Error: {result.get('error', 'Unknown error')}"
                
        except Exception as e:
            return f"Sorry, there was an error searching for flights: {str(e)}"
    else:
        missing = sm.get_missing_variables()
        return f"Flight search in progress. Still need: {', '.join(missing)}. Please provide these details to continue."

def format_duration(minutes: int) -> str:
    """Format duration in minutes to Xh Ym"""
    if not minutes:
        return "Unknown"
    hours = minutes // 60
    mins = minutes % 60
    if hours and mins:
        return f"{hours}h {mins}m"
    elif hours:
        return f"{hours}h"
    else:
        return f"{mins}m"

def format_stops(stops: int) -> str:
    """Format stops count"""
    if stops == 0:
        return "non-stop"
    elif stops == 1:
        return "1 stop"
    else:
        return f"{stops} stops"

def format_baggage_summary(baggage: dict) -> str:
    """Format baggage information"""
    parts = []
    
    # Carry-on
    carry_on = "✓" if baggage.get("carry_on_included") else "✗"
    carry_text = baggage.get("carry_on_text", "")
    if carry_text:
        parts.append(f"carry-on {carry_on} ({carry_text})")
    else:
        parts.append(f"carry-on {carry_on}")
    
    # Checked bag
    checked = "✓" if baggage.get("checked_bag_included") else "✗"
    parts.append(f"checked {checked}")
    
    # Validating airline
    if baggage.get("validating_airline"):
        parts.append(f"Validating airline: {baggage['validating_airline']}")
    
    # Penalties
    if baggage.get("penalties_change"):
        parts.append(f"Change: {baggage['penalties_change']}")
    if baggage.get("penalties_cancel"):
        parts.append(f"Cancel: {baggage['penalties_cancel']}")
    
    return " | ".join(parts)



# Making the tools callable - only expose FlightSearchStateMachine to LLM
tools = [FlightSearchStateMachine]

# Using AI model
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 
llm = init_chat_model("gpt-4o-mini", model_provider="openai", temperature=0)

# Creating state graph
class State(TypedDict):
    messages: Annotated[list[dict], add_messages]

graph_b = StateGraph(State)
llm_with_tools = llm.bind_tools(tools)

# Adding first node
def chatbot(state: State):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

graph_b.add_node("chatbot", chatbot)

# Creating tool node
from langchain_core.messages import ToolMessage

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
            # Pass thread_id and user_input_text to FlightSearchStateMachine if needed
            tool_args = tool_call["args"]
            if tool_call["name"] == "FlightSearchStateMachine":
                if "thread_id" not in tool_args:
                    # Extract thread_id from the graph state if available
                    tool_args["thread_id"] = inputs.get("configurable", {}).get("thread_id", "default")
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

tool_node = BasicToolNode(tools=tools)
graph_b.add_node("tools", tool_node)

# Routing function
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

# Compiling the graph
graph_b.add_conditional_edges(
    "chatbot",
    route_tools,
    {"tools": "tools", END: END},
)
# Any time a tool is called, we return to the chatbot to decide the next step
graph_b.add_edge("tools", "chatbot")
graph_b.add_edge(START, "chatbot")
graph = graph_b.compile()

# Adding memory checkpoint
memory = InMemorySaver()
graph = graph_b.compile(checkpointer=memory)

app = FastAPI()

def _extract_last_ai_text(state: dict) -> str:
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

@app.get("/")
async def healthcheck():
    return {"status": "ok"}

@app.post("/webhook")
async def twilio_whatsapp(Body: str = Form(...), From: str | None = Form(default=None), WaId: str | None = Form(default=None)):
    thread_id = WaId or From or "whatsapp-default"
    try:
        from langchain_core.messages import HumanMessage
        state = graph.invoke(
            {"messages": [HumanMessage(content=Body)]},
            {"configurable": {"thread_id": thread_id}},
        )
        reply_text = _extract_last_ai_text(state) or "Got it."
    except Exception as e:
        reply_text = f"Error: {e}"
    # Return TwiML so Twilio replies to the user
    twiml = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>{html.escape(reply_text)}</Message></Response>"
    return Response(content=twiml, media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("actual_app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)

