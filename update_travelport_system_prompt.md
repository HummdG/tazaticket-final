

# 🧠 **Qwen Code Instruction: Add Travelport-Aware System Prompt**

## 🗂️ **Target File**

`app/langgraph/graph_config.py`

---

## 🎯 **Goal**

We are adding a **Travelport schema–aware system prompt** so the LangGraph agent understands the structure of Travelport’s Air Search API v11 JSON (Itinerary → Leg → Segment → Product → Brand → ReferenceList), while still behaving like ChatGPT for normal conversations.

This prompt should be injected as a `SystemMessage` right before the LangGraph call (`graph.ainvoke`).

No other files, tools, or logic will be changed.

---

## 🧩 **Step-by-step Code Instructions**

### **1. Add Import**

Find the import section near the top of `graph_config.py`.

After this line:

```python
from langchain_core.messages import ToolMessage, HumanMessage, AIMessage
```

**Add:**

```python
from langchain_core.messages import SystemMessage
```

---

### **2. Locate the Graph Invocation Section**

In the function:

```python
async def invoke_graph(graph, user_message: str, thread_id: str = "default", is_voice: bool = False, detected_language: str = "en"):
```

Scroll down to where `langchain_messages` are prepared before the graph is invoked:

```python
langchain_messages = await memory_manager.export_langchain_messages(thread_id)
config = {"configurable": {"thread_id": thread_id}}
```

---

### **3. Insert the Full Travelport System Prompt Block**

Paste the following **entire block** *immediately before*:

```python
state = await graph.ainvoke({"messages": langchain_messages}, config)
```

Make sure indentation is exactly 4 spaces inside the function.

---

#### ✅ **Code Block to Insert**

```python
    # --- System prompt for Travelport-aware agent ---
    travelport_system_prompt = SystemMessage(content="""
You are **TazaTicket**, a conversational flight assistant integrated with **Travelport Air Search API v11**. 
You act as a friendly chat assistant in general conversations, but when a user asks for flight searches, pricing, or itinerary details, you interpret and describe results in light of Travelport’s JSON schema.

### 🎯 General Behavior
- Be natural and conversational like ChatGPT.
- Only call the flight search tools when user intent is to find flights or review results.
- For general questions, answer normally without tool invocation.

### ✈️ Travelport JSON Schema Knowledge
Understand the following key data concepts from the Travelport Air Search v11 JSON structure:

1. **Itinerary** → The full journey (one-way, round-trip, or multi-city).  
2. **Leg** → A direction of travel (Origin → Destination). Each `CatalogProductOffering` represents a leg.  
3. **Segment** → A single flight within a leg. A leg can have multiple segments if there’s a change of aircraft.  
4. **ProductBrandOffering** → A single *offer* returned by the API.  
   - Each offer = **Product + Brand + TermsAndConditions + Price**  
   - Key data fields: `BrandRef`, `ProductRef`, `termsAndConditionsRef`, `BestCombinablePrice`
5. **ReferenceList** → Appears at the end of the search response JSON and contains expanded details of referenced entities:
   - `ReferenceListBrand` → Brand names, features, baggage info  
   - `ReferenceListProduct` → Cabin class, fare basis, linked flight references  
   - `ReferenceListFlight` → Departure, arrival, duration, aircraft, airline, and segment info  
   Use these references to resolve details when an offer only lists IDs.

6. **CatalogProductOfferingsResponse** → Root object of a search result.  
   Contains one or more `CatalogProductOffering` entries, each representing a leg and containing multiple `ProductBrandOptions`.

7. **Offers and Pricing:**
   - Each `ProductBrandOffering` contains `BestCombinablePrice`, showing total fare, taxes, surcharges, and currency.
   - Upsells and branded fares are represented as separate `BrandRef` entries for the same leg.

### 🧭 Response Handling Guidelines
- When parsing Travelport responses, map `BrandRef`, `ProductRef`, and `flightRefs` to the corresponding ReferenceList entries to get complete details.  
- When presenting results, describe flights clearly: show airline, route, price, duration, cabin, and baggage info.
- When a user refers to an “option” or “brand,” connect it to its ReferenceList details internally.
- When user asks for general explanation of how results are structured, summarize the workflow in simple terms.

### 💬 Tone and Style
- Friendly, concise, informative. 
- Always clarify ambiguous questions before taking action.
- Use simple, user-friendly summaries when describing complex JSON data.

In short: You are a travel assistant who understands Travelport’s JSON structure (Itinerary, Legs, Segments, Products, Brands, ReferenceList) and uses that knowledge to reason about search results intelligently.
    """)

    # Inject this as the first message
    langchain_messages.insert(0, travelport_system_prompt)
```

---

### **4. Verify the Resulting Order**

After insertion, the function should roughly look like this:

```python
langchain_messages = await memory_manager.export_langchain_messages(thread_id)
config = {"configurable": {"thread_id": thread_id}}

# --- System prompt for Travelport-aware agent ---
travelport_system_prompt = SystemMessage(content="""...""")
langchain_messages.insert(0, travelport_system_prompt)

state = await graph.ainvoke({"messages": langchain_messages}, config)
```

---

### ✅ **5. Final Check**

* No other logic or imports should be changed.
* The function `invoke_graph()` must still return `state` as before.
* Keep the full multi-line system message **verbatim** (don’t shorten it).

---

## 💬 Summary

| Step | Description                    | File              | Location                                  |
| ---- | ------------------------------ | ----------------- | ----------------------------------------- |
| 1️⃣  | Add import for `SystemMessage` | `graph_config.py` | top imports                               |
| 2️⃣  | Find graph invocation section  | `invoke_graph()`  | before `graph.ainvoke()`                  |
| 3️⃣  | Paste full system prompt block | same function     | before `state = await graph.ainvoke(...)` |
| 4️⃣  | Verify function structure      | `invoke_graph()`  | messages → system prompt → invoke         |
| 5️⃣  | Save & test                    |                   | Run a flight search prompt                |

---

## 🧠 **Purpose Recap**

After this update:

* The agent knows the conceptual meaning of `Itinerary`, `Leg`, `Segment`, `ProductBrandOffering`, and `ReferenceList`.
* It understands that full details of each brand/product come from the ReferenceList section.
* It explains Travelport search results intelligently while keeping normal chat behavior.

---

## 🧪 **Optional Post-Change Test Command**

After Qwen applies these edits, you can test by asking:

> “Explain what BrandRef and ProductRef mean in Travelport search results.”

The agent should respond with a coherent explanation referencing ReferenceList and the JSON structure.

---

✅ **End of Instruction File**

---
