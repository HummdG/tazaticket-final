✦ Complete Call Chain Trace: Text Message Processing

  1. Webhook Reception
   - Entry Point: main.py - @app.post("/webhook") endpoint
   - Function: twilio_whatsapp()
   - Process:
     - Receives POST request from Twilio with message content in the Body parameter
     - Extracts thread_id from WaId or From parameters

  2. Voice Message Check
   - Process: Checks if MediaUrl0 exists and is an audio content type
   - Action: If it's a voice message, queues background processing via queue_voice_processing()
   - Action: If it's a text message, continues to text processing

  3. Language Detection
   - Translation Service Access: Gets translation_service from `app.state.translation_service`
   - Language Detection: Calls await translation_service.detect_and_translate_to_english(Body)
   - Decision Point: Checks if detected_language != "en" (non-English) to route to background processing

  4. Text Processing Path Split
   - English Messages: Process synchronously as described in sections 5-10 below
   - Non-English Messages: Route to background processing via queue_text_processing()
     a. queue_text_processing() queues the message using the same infrastructure as voice messages
     b. Returns immediate acknowledgment: "Got your message! We're working on it and will respond shortly..."
     c. Actual processing happens asynchronously in process_text_message_background()

  5. Synchronous Text Processing (English Messages)
   - Graph Service Access: Gets graph from app.state.graph
   - Graph Invocation: Calls await invoke_graph(graph, english_text, thread_id, detected_language=detected_language)

  6. LangGraph Configuration
   - File: app/langgraph/graph_config.py
   - Function: invoke_graph() (now async)
   - Process Flow:
    a. Sets global _current_thread_id to the current thread_id
    b. Calls await memory_manager.on_session_start(thread_id)
    c. Calls await memory_manager.add_user_message(thread_id, user_message)
    d. Calls await memory_manager.get_context_for_llm(thread_id)
    e. Converts context messages to LangChain message format
    f. Creates configuration with thread_id, voice mode, and detected language
    g. Invokes the graph with messages and config
    h. Extracts assistant response using extract_last_ai_text(state)
    i. If assistant response exists, calls await memory_manager.add_assistant_message(thread_id, assistant_text)

  7. Memory Manager Operations
   - File: app/langgraph/memory_manager.py
   - Operations:
    a. on_session_start(): Initializes session and loads context from DynamoDB
    b. add_user_message(): Adds user message and starts a new pair
    c. get_context_for_llm(): Gets flattened context for LLM (last 15 pairs)
    d. add_assistant_message(): Adds assistant message and closes current pair

  8. Thread State Handling
   - File: app/langgraph/memory_utils.py
   - Classes: ThreadState, Pair, Message
   - Storage: ThreadState objects are stored in Redis using _save_thread_state_to_redis() method
   - Retrieval: ThreadState objects are loaded from Redis using _get_thread_state() method

  9. Redis Operations (Memory Manager)
   - Retrieval Process in _get_thread_state():
    a. Gets thread state from Redis: thread_data = await redis_conn.get(thread_state_key)
    b. Deserializes JSON: thread_dict = json.loads(thread_data)
    c. FIXED: Now uses ThreadState.from_dict(thread_dict) to properly reconstruct Pair objects
    d. Returns fully constructed ThreadState object

   - Storage Process in _save_thread_state_to_redis():
    a. Manually creates serializable dictionary with thread state data
    b. Calls json.dumps(thread_dict) to serialize for Redis storage

  10. Graph Processing
   - File: app/langgraph/graph_config.py
   - Result: Returns graph state containing the AI response

  11. Synchronous Response Formatting (English Messages)
   - Back to: main.py - webhook function
   - Reverse Translation: If detected language ≠ "en", translate response back using await translation_service.translate_from_english(reply_text,
     detected_language)
   - TWIML Generation: Creates XML response for Twilio
   - Return: Returns XML response to Twilio immediately

  12. Background Text Processing (Non-English Messages)
   - Function: process_text_message_background() (in main.py)
   - Process Flow:
     a. Language Detection and Translation: Translates original text to English using detect_and_translate_to_english()
     b. Graph Processing: Invokes LangGraph with English text to get AI response
     c. Reverse Translation: Translates response back to the detected language using translate_from_english()
     d. Response Delivery: Sends the final response via Twilio using send_twilio_message()

  13. Background Processing Infrastructure
   - Uses the same async worker infrastructure as voice messages
   - Leverages queue_voice_task() function to queue tasks for background processing
   - Provides immediate response to prevent 499 timeout errors
   - Maintains same functionality while ensuring fast webhook response

  Potential Error Points for ThreadState Serialization Error:
   1. In `_save_thread_state_to_redis()`: If the thread_state object still contains non-serializable elements
   2. In Redis operations: When storing serialized ThreadState data
   3. In `_get_thread_state()`: When reconstructing ThreadState from Redis data

  The error is most likely occurring in the _save_thread_state_to_redis() method when json.dumps(thread_dict) is called, indicating that one of the
  fields in thread_dict still contains a non-serializable object, possibly related to the lock field in ThreadState or some other non-serializable
  element.

