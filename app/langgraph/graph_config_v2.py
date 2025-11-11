# app/langgraph/graph_config_v2.py
from langchain_core.tools import tool
from langgraph.graph import StateGraph
from app.tools.FlightSearchFSM_v2 import FlightSearchFSM_v2
from app.tools.UnifiedTravelportBooking_v2 import UnifiedTravelportBooking_v2

# Define the state structure
class State:
    def __init__(self):
        self.messages = []
        self.search_id = None
        self.selected_offer = None
        self.travelers = []

# Create a simple deterministic graph
def create_deterministic_graph():
    graph = StateGraph(State)
    
    # Add nodes for our FSM and booking tool
    graph.add_node("flight_search", lambda state: {"search_id": FlightSearchFSM_v2()})
    graph.add_node("booking", lambda state: {"booking_result": UnifiedTravelportBooking_v2()})
    
    # Define the flow: start -> flight_search -> booking -> end
    graph.add_edge("__start__", "flight_search")
    graph.add_edge("flight_search", "booking")
    graph.add_edge("booking", "__end__")
    
    return graph.compile()

# Example usage
deterministic_workflow = create_deterministic_graph()