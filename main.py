import os
import html
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Form
from fastapi.responses import Response
from dotenv import load_dotenv

# --- Load environment variables ---
load_dotenv()

# --- LangGraph core imports ---
from app.langgraph.graph_config import create_graph, invoke_graph, extract_last_ai_text

# --- Search Result Management ---
from app.services.search_result_manager import search_result_manager

# --- Services ---
from app.services.translation_service import TranslationService

# --- Voice processing components ---
from app.speech.speech_processor import queue_voice_task, process_voice_message_background

# -------------------------------------------------------
#   FastAPI Application Setup with Lifespan Management
# -------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and clean up shared async resources."""
    print("🚀 Starting up Tazaticket application...")

    # Initialize translation service
    translation_service = TranslationService()
    app.state.translation_service = translation_service
    print("🌐 Translation service initialized")

    # Initialize LangGraph (shared instance)
    graph = create_graph()
    app.state.graph = graph
    print("🧠 LangGraph initialized")

    # Initialize memory monitoring
    from app.langgraph.memory_manager import memory_manager
    await memory_manager.start_periodic_redis_memory_check()
    print("📊 Redis memory monitoring started")

    yield  # Application runs here

    print("🛑 Shutting down Tazaticket application...")
    await memory_manager.shutdown()
    print("💾 Memory manager shut down")


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def healthcheck():
    """Simple healthcheck endpoint."""
    return {"status": "ok"}


# -------------------------------------------------------
#   Voice Message Queueing
# -------------------------------------------------------
def queue_voice_processing(media_url: str, thread_id: str, from_number: str) -> str:
    """Queue voice message for background processing and return immediate response."""
    try:
        print(f"🎤 Queueing voice message for background processing: {media_url} (thread={thread_id}, from={from_number})")
        queue_voice_task(process_voice_message_background, media_url, thread_id, from_number)
        print(f"🎤 Voice message queued successfully for thread {thread_id}")
        return "🎤 Voice message received — processing in background..."
    except Exception as e:
        import traceback
        print(f"❌ Error queueing voice processing for {thread_id}: {e}")
        traceback.print_exc()
        return "Sorry, there was an error processing your voice message."


# -------------------------------------------------------
#   Text Message Queueing (Unified Path)
# -------------------------------------------------------
def queue_text_processing(user_message: str, thread_id: str, from_number: str, detected_language: str) -> str:
    """Queue *all* text messages for background processing and return immediate response."""
    try:
        print(f"💬 Queueing text message for background processing: '{user_message[:80]}...' (thread={thread_id}, lang={detected_language})")
        queue_voice_task(process_text_message_background, user_message, thread_id, from_number, detected_language)
        return "💬 Message received — processing in background..."
    except Exception as e:
        import traceback
        print(f"❌ Error queueing text message for {thread_id}: {e}")
        traceback.print_exc()
        return "Sorry, there was an error queueing your message."


# -------------------------------------------------------
#   Background Text Processing
# -------------------------------------------------------
async def process_text_message_background(user_message: str, thread_id: str, from_number: str, detected_language: str):
    """Async pipeline for handling all queued text messages (English or non-English)."""
    import time, sys
    try:
        print(f"[{time.strftime('%H:%M:%S')}] [TextProcessor] ▶ Start background task for {thread_id} (lang={detected_language})", flush=True)

        # Step 1: Detect and translate to English
        translation_service = app.state.translation_service
        _, english_text = await translation_service.detect_and_translate_to_english(user_message)
        if english_text is None:
            english_text = user_message
            print(f"[{time.strftime('%H:%M:%S')}] [TextProcessor] ⚠️ Translation failed, using original text.", flush=True)
        else:
            print(f"[{time.strftime('%H:%M:%S')}] [TextProcessor] ✅ Translated to English successfully.", flush=True)

        # Step 2: Run LangGraph pipeline
        from app.langgraph.memory_manager import memory_manager
        graph = create_graph()

        await memory_manager.on_session_start(thread_id)
        await memory_manager.add_user_message(thread_id, english_text)
        state = await invoke_graph(graph, english_text, thread_id, detected_language=detected_language)
        reply_text = extract_last_ai_text(state) or "Got it."

        # Check if this response contains search results that should be stored
        if hasattr(state, 'get') and state.get('messages'):
            # Look for tool calls that might have generated search results
            for message in state['messages']:
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    for tool_call in message.tool_calls:
                        if tool_call.get('name') in ['TravelportSearch', 'BulkFlightSearch']:
                            # This was a search operation, but we need to check if we can extract results
                            # The actual search results would be in the tool response
                            pass

        print(f"[{time.strftime('%H:%M:%S')}] [TextProcessor] 🧠 Graph completed — reply extracted.", flush=True)

        # Step 3: Translate response back if needed
        if detected_language != "en":
            translated_reply = await translation_service.translate_from_english(reply_text, detected_language)
            if translated_reply:
                reply_text = translated_reply
                print(f"[{time.strftime('%H:%M:%S')}] [TextProcessor] 🌐 Reply translated back to {detected_language}.", flush=True)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] [TextProcessor] ⚠️ No reverse translation, keeping English.", flush=True)
        else:
            print(f"[{time.strftime('%H:%M:%S')}] [TextProcessor] Reply already in English.", flush=True)

        # Step 4: Send final reply via Twilio
        from app.speech.speech_processor import send_twilio_message
        await send_twilio_message(from_number, reply_text, thread_id)
        print(f"[{time.strftime('%H:%M:%S')}] [TextProcessor] ✅ Completed for {thread_id}", flush=True)

    except Exception as e:
        import traceback
        print(f"[{time.strftime('%H:%M:%S')}] [TextProcessor] ❌ Error in background task for {thread_id}: {e}", flush=True)
        traceback.print_exc()
        from app.speech.speech_processor import send_twilio_message
        await send_twilio_message(from_number, "Sorry, there was an error processing your message.", thread_id)
        sys.stdout.flush()


# -------------------------------------------------------
#   Main Webhook Endpoint
# -------------------------------------------------------
@app.post("/webhook")
async def twilio_whatsapp(
    Body: str = Form(default=""),
    From: str | None = Form(default=None),
    WaId: str | None = Form(default=None),
    MediaUrl0: str | None = Form(default=None),
    MediaContentType0: str | None = Form(default=None)
):
    """Twilio WhatsApp webhook — routes all messages through background queue."""
    thread_id = WaId or From or "whatsapp-default"
    print(f"[Webhook] 🔗 New message from {From}, thread_id={thread_id}")

    try:
        # Handle unsupported media
        if MediaUrl0 and MediaContentType0 and not MediaContentType0.startswith("audio/"):
            reply_text = "Sorry, I can only process text messages and voice notes."
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
                        <Response><Message>{html.escape(reply_text)}</Message></Response>"""
            return Response(content=twiml, media_type="application/xml")

        # Handle voice message
        if MediaUrl0 and MediaContentType0 and MediaContentType0.startswith("audio/"):
            queue_voice_processing(MediaUrl0, thread_id, From)
            twiml = """<?xml version="1.0" encoding="UTF-8"?><Response></Response>"""
            return Response(content=twiml, media_type="application/xml")

        # Handle text message (always queued)
        translation_service = app.state.translation_service
        detected_language, _ = await translation_service.detect_and_translate_to_english(Body)

        # Always send to queue (English or not)
        queue_text_processing(Body, thread_id, From, detected_language)

        # Return empty TwiML (instant Twilio ack)
        twiml = """<?xml version="1.0" encoding="UTF-8"?><Response></Response>"""
        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        print(f"❌ Error in webhook: {e}")
        reply_text = "Sorry, something went wrong."
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Message>{html.escape(reply_text)}</Message></Response>"""
        return Response(content=twiml, media_type="application/xml")


# -------------------------------------------------------
#   Entry Point
# -------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
