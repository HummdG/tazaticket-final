# LangGraph Agent Flow

┌─────────────────────────────────────────────────────────────────────────────┐
│                                   START                                     │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ invoke_graph(user_message, thread_id, is_voice, detected_language)          │
│ ├─ memory_manager.on_session_start(thread_id)                               │
│ └─ memory_manager.add_user_message(thread_id, user_message)                 │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Build LLM Context                                                           │
│ ├─ memory_manager.get_context_for_llm(thread_id)                            │
│ └─ Merge with system prompt                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Chatbot Node (LLM with Tools)                                               │
│ ├─ llm_with_tools = llm.bind_tools(tools)                                   │
│ └─ llm_with_tools.ainvoke(state["messages"])                                │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ route_tools() Decision                                                      │
│ ├─ If last AI message has tool_calls → "tools" node                         │
│ └─ Else → END                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ├Yes
        │                              
        ▼                              
┌─────────────────────────────────────────────────────────────────────────────┐
│ BasicToolNode (tools node)                                                  │
│ ├─ Iterate over tool_calls                                                  │
│ │   ├─ Inject: thread_id, mode, language                                    │
│ │   ├─ If FlightSearch/BulkSearch: add user_input_text                      │
│ │   ├─ Call tool.ainvoke() or tool.invoke()                                 │
│ │   └─ Create ToolMessage(content=str(result))                              │
│ └─ Return {"messages": [ToolMessage(...)]}                                  │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Edge: tools → chatbot                                                       │
│ └─ Loop back to chatbot node                                                │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Chatbot Node (Round 2)                                                      │
│ ├─ Receives ToolMessages as context                                         │
│ ├─ LLM may produce new tool calls → repeat loop                             │
│ └─ Or produce final assistant text                                          │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Extract Assistant Message                                                   │
│ ├─ assistant_text = extract_last_ai_text(state)                             │
│ ├─ memory_manager.add_assistant_message(thread_id, assistant_text)          │
│ └─ if exception → store fallback message                                    │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                   END                                       │
└─────────────────────────────────────────────────────────────────────────────┘

