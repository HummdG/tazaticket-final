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

load_dotenv()
# Making the tool callable
@tool("TravelportSearch")
def TravelportSearch(departure_date:str, from_city:str, to_city:str, carrier:str):

	"""This tool calls the travelport rest api to get teh cheapest flight possible for the user's given parameters"""
	load_dotenv()  # Reads .env in current directory

	CLIENT_ID       = os.getenv("TRAVELPORT_CLIENT_ID")
	CLIENT_SECRET   = os.getenv("TRAVELPORT_CLIENT_SECRET")
	USERNAME        = os.getenv("TRAVELPORT_USERNAME")
	PASSWORD        = os.getenv("TRAVELPORT_PASSWORD")
	ACCESS_GROUP    = os.getenv("TRAVELPORT_ACCESS_GROUP")

	OAUTH_URL       = "https://oauth.pp.travelport.com/oauth/oauth20/token"
	CATALOG_URL     = "https://api.pp.travelport.com/11/air/catalog/search/catalogproductofferings"
	AIRPRICE_URL     = "https://api.pp.travelport.com/11/air/price/offers/buildfromcatalogproductofferings"

	def fetch_password_token():
		data = {
			"grant_type":    "password",
			"username":      USERNAME,
			"password":      PASSWORD,
			"client_id":     CLIENT_ID,
			"client_secret": CLIENT_SECRET,
			"scope":         "openid"
		}
		resp = requests.post(
			OAUTH_URL,
			headers={"Content-Type": "application/x-www-form-urlencoded"},
			data=data
		)
		resp.raise_for_status()
		return resp.json()["access_token"]

	token = fetch_password_token()
	# print(f"🔑 Token obtained: {token[:20]}…")

	headers = {
	"Accept":                       "application/json",
	"Content-Type":                 "application/json",
	"Accept-Encoding":              "gzip, deflate",
	"Cache-Control":                "no-cache",
	"Authorization":                f"Bearer {token}",
	"XAUTH_TRAVELPORT_ACCESSGROUP": ACCESS_GROUP,
	"Accept-Version":               "11",
	"Content-Version":              "11",
	}
	# print("📋 Headers built")

	carrier_list = [carrier]

	# Now build the payload using those real date strings:
	payload = {
		"@type": "CatalogProductOfferingsQueryRequest",
		"CatalogProductOfferingsRequest": {
			"@type": "CatalogProductOfferingsRequestAir",
			"maxNumberOfUpsellsToReturn": 1,
			"contentSourceList": ["GDS"],
			"PassengerCriteria": [
				{
					"@type": "PassengerCriteria",
					"number": 1,
					"age": 25,
					"passengerTypeCode": "ADT"
				}
			],
			"SearchCriteriaFlight": [
				{
					"@type": "SearchCriteriaFlight",
					"departureDate": departure_date,   # injected here
					"From": {"value": from_city},
					"To":   {"value": to_city}
				},
				
			],
			"SearchModifiersAir": {
				"@type": "SearchModifiersAir",
				"CarrierPreference": [
					{
						"@type": "CarrierPreference",
						"preferenceType": "Preferred",
						"carriers": carrier_list
					}
				]
			},
			"CustomResponseModifiersAir": {
				"@type": "CustomResponseModifiersAir",
				"SearchRepresentation": "Journey"
			}
		}
	}

	response = requests.post(CATALOG_URL, headers=headers, json=payload)
	try:
		response.raise_for_status()
		result = response.json()
		import json
		# print(json.dumps(result, indent=2))
	except requests.HTTPError as e:
		print("❌ Request failed:", e)
		print(response.status_code, response.text)

	cheapest_flight_price = result["CatalogProductOfferingsResponse"]["CatalogProductOfferings"]["CatalogProductOffering"][0]["ProductBrandOptions"][0]["ProductBrandOffering"][0]["BestCombinablePrice"]["TotalPrice"]

	return cheapest_flight_price

# Making the tool
tool = TravelportSearch if hasattr(TravelportSearch, "invoke") else lc_tool("TravelportSearch")(TravelportSearch)
tools = [tool]

# using ai model

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 

llm = init_chat_model("gpt-4o-mini", model_provider="openai", temperature=0)

# creating state graph
class State(TypedDict):
	messages: Annotated[list[dict], add_messages]

graph_b = StateGraph(State)

llm_with_tools= llm.bind_tools(tools)

# adding first node
def chatbot(state:State):
	return {"messages": [llm_with_tools.invoke(state["messages"])]}


graph_b.add_node("chatbot", chatbot)

# creating tool node
from langchain_core.messages import ToolMessage

class BasicToolNode:
	"""Node that runs the tools requested in the last AI message."""

	def __init__(self, tools: list)-> None:
		self.tools_by_name = {tool.name:tool for tool in tools}

	def __call__(self, inputs: dict):
		if messages := inputs.get("messages", []):
			message = messages[-1]
		else:
			raise ValueError("No messages in inputs")
		
		outputs = []
		for tool_call in message.tool_calls:
			tool_result = self.tools_by_name[tool_call["name"]].invoke(
				tool_call["args"]
			)
			outputs.append(
				ToolMessage(
					content=tool_result,
					name=tool_call["name"],
					tool_call_id=tool_call["id"],
				)
			)
		return {"messages": outputs}
	


tool_node = BasicToolNode(tools=[tool])

graph_b.add_node("tools", tool_node)

# routing function
def route_tools(
	state: State,
):

	"""
		Use in the conditional_edge to route to the ToolNode if the last message
		has tool calls. Otherwise, route to the end.
	"""
	if isinstance(state, list):
		ai_message = state[-1]
	elif messages:=state.get("messages", []):
		ai_message = messages[-1]
	else:
		raise ValueError("No messages in state", {state})
	if hasattr(ai_message, "tool_calls") and len(ai_message.tool_calls) > 0:
		return "tools"
	
	return END

# compiling the graph
graph_b.add_conditional_edges(
	"chatbot",
	route_tools,
	# The following dictionary lets you tell the graph to interpret the condition's outputs as a specific node
	# It defaults to the identity function, but if you
	# want to use a node named something else apart from "tools",
	# You can update the value of the dictionary to something else
	# e.g., "tools": "my_tools"
	{"tools": "tools", END: END},
)
# Any time a tool is called, we return to the chatbot to decide the next step
graph_b.add_edge("tools", "chatbot")
graph_b.add_edge(START, "chatbot")
graph = graph_b.compile()

# adding memory checkpoint
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
		state = graph.invoke(
			{"messages": [{"role": "user", "content": Body}]},
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

