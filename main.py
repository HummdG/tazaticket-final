import os 
from dotenv import load_dotenv
import html

from contextlib import asynccontextmanager
from fastapi import FastAPI, Form
from fastapi.responses import Response

# Import our LangGraph configuration
from app.langgraph.graph_config import create_graph, invoke_graph, extract_last_ai_text

# Import services
from app.services.translation_service import TranslationService

# Import voice processing components
from app.speech.speech_processor import queue_voice_task, process_voice_message_background

# Create FastAPI app with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize async resources
    print("🚀 Starting up Tazaticket application...")
    
    # Initialize translation service
    translation_service = TranslationService()
    app.state.translation_service = translation_service
    print("🌐 Translation service initialized")
    
    # Initialize LangGraph
    graph = create_graph()
    app.state.graph = graph
    print("🧠 LangGraph initialized")
    
    # Initialize and start Redis memory monitoring
    from app.langgraph.memory_manager import memory_manager
    await memory_manager.start_periodic_redis_memory_check()
    print("📊 Redis memory monitoring started")
    
    yield  # The application runs during this part
    
    # Shutdown: Clean up resources
    print("🛑 Shutting down Tazaticket application...")
    
    # Close translation service if needed
    # Currently, TranslationService doesn't have a close method, but we could add one if needed
    # await translation_service.aclose() if hasattr(translation_service, 'aclose') else None
    
    # Close memory manager if needed
    await memory_manager.shutdown()
    print("💾 Memory manager shut down")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def healthcheck():
    return {"status": "ok"}

def queue_voice_processing(media_url: str, thread_id: str, from_number: str) -> str:
    """Queue voice message for background processing and return immediate response"""
    try:
        print(f"🎤 Queueing voice message for background processing: {media_url} (thread: {thread_id}, from: {from_number})")
        
        # Queue the heavy processing for background
        task_future = queue_voice_task(process_voice_message_background, media_url, thread_id, from_number)
        print(f"🎤 Voice message queued successfully for thread {thread_id}, task future: {task_future}")
        
        return "🎤 Got your voice message! We're working on it and will respond shortly..."
        
    except Exception as e:
        import traceback
        print(f"❌ Error queueing voice processing for {thread_id}: {e}")
        print(f"❌ Error traceback for {thread_id}:")
        traceback.print_exc()
        return "Sorry, there was an error processing your voice message."


def queue_text_processing(user_message: str, thread_id: str, from_number: str, detected_language: str) -> str:
    """Queue non-English text message for background processing and return immediate response"""
    try:
        print(f"💬 Queueing text message for background processing: '{user_message[:50]}...' (thread: {thread_id}, from: {from_number}, lang: {detected_language})")
        
        # Queue the heavy processing for background
        task_future = queue_voice_task(process_text_message_background, user_message, thread_id, from_number, detected_language)
        print(f"💬 Text message queued successfully for thread {thread_id}, task future: {task_future}")
        
        return "💬 Got your message! We're working on it and will respond shortly..."
        
    except Exception as e:
        import traceback
        print(f"❌ Error queueing text processing for {thread_id}: {e}")
        print(f"❌ Error traceback for {thread_id}:")
        traceback.print_exc()
        return "Sorry, there was an error processing your message."


async def process_text_message_background(user_message: str, thread_id: str, from_number: str, detected_language: str):
    """Async processing pipeline for a single non-English text message."""
    try:
        print(f"[TextProcessor] Starting background processing for {thread_id} from {from_number} in {detected_language}")
        
        # 1) Use the original text for translation to English 
        print(f"[TextProcessor] Translation: Starting translation to English for {thread_id}")
        translation_service = app.state.translation_service
        _, english_text = await translation_service.detect_and_translate_to_english(user_message)
        if english_text is None:
            # Translation failed, use original text
            english_text = user_message
            print(f"[TextProcessor] Translation: Translation failed for {thread_id}, using original text")
        else:
            print(f"[TextProcessor] Translation: Successfully translated to English for {thread_id}")
        
        # 2) Run LangGraph (sync functions run in thread)
        print(f"[TextProcessor] LangGraph: Starting invocation for {thread_id}")
        from app.langgraph import create_graph, invoke_graph, extract_last_ai_text
        graph = await asyncio.to_thread(create_graph)
        print(f"[TextProcessor] LangGraph: Graph created successfully for {thread_id}")
        state = await asyncio.to_thread(invoke_graph, graph, english_text, thread_id, detected_language=detected_language)
        print(f"[TextProcessor] LangGraph: Graph invocation completed for {thread_id}")
        reply_text = await asyncio.to_thread(extract_last_ai_text, state) or "Got it."
        print(f"[TextProcessor] LangGraph: Extracted AI response for {thread_id}: '{reply_text[:50]}...'")
        
        # 3) Translate back to detected language if needed
        print(f"[TextProcessor] Reverse Translation: Starting for {thread_id}")
        if detected_language != "en":
            try:
                translated_reply = await translation_service.translate_from_english(reply_text, detected_language)
                if translated_reply:
                    reply_text = translated_reply
                    print(f"[TextProcessor] Reverse Translation: Successfully translated back to {detected_language} for {thread_id}")
                else:
                    print(f"[TextProcessor] Reverse Translation: No translation returned for {thread_id}, keeping English response")
            except Exception as e:
                print(f"[TextProcessor] Reverse Translation: Exception occurred while translating back for {thread_id}: {e}")
        else:
            print(f"[TextProcessor] Reverse Translation: No reverse translation needed for {thread_id}, already English")
        
        # 4) Send response via Twilio (async HTTP)
        print(f"[TextProcessor] Twilio: Starting response sending for {thread_id}")
        from app.speech.speech_processor import send_twilio_message
        await send_twilio_message(from_number, reply_text, thread_id)
        print(f"[TextProcessor] Completed processing for {thread_id}")
        
    except Exception as e:
        import traceback
        print(f"[TextProcessor] Background processing error for {thread_id}: {e}")
        print(f"[TextProcessor] Error traceback for {thread_id}:")
        traceback.print_exc()
        from app.speech.speech_processor import send_twilio_message
        await send_twilio_message(from_number, "Sorry, there was an error processing your message.", thread_id)

@app.post("/webhook")
async def twilio_whatsapp(
    Body: str = Form(default=""), 
    From: str | None = Form(default=None), 
    WaId: str | None = Form(default=None),
    MediaUrl0: str | None = Form(default=None),
    MediaContentType0: str | None = Form(default=None)
):
    thread_id = WaId or From or "whatsapp-default"
    
    try:
        # Check for unsupported media types (images, videos, GIFs, etc.)
        if MediaUrl0 and MediaContentType0:
            is_voice_message = MediaContentType0.startswith('audio/')
            
            if not is_voice_message:
                # Reject unsupported media types
                reply_text = "Sorry, I can only process text messages and voice notes. Please send your message as text or a voice note."
                twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
                <Response>
                    <Message>{html.escape(reply_text)}</Message>
                </Response>"""
                return Response(content=twiml, media_type="application/xml")
        
        # Check if this is a voice message
        is_voice_message = (MediaUrl0 and 
                           MediaContentType0 and 
                           MediaContentType0.startswith('audio/'))
        
        if is_voice_message:
            # Queue voice message for background processing
            reply_text = queue_voice_processing(MediaUrl0, thread_id, From)
            
            # Return immediate acknowledgment
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Message>{html.escape(reply_text)}</Message>
            </Response>"""
        else:
            # Process text message with language detection
            translation_service = app.state.translation_service
            detected_language, english_text = await translation_service.detect_and_translate_to_english(Body)
            

            if english_text is None:
                # Translation failed, use original text
                english_text = Body
                detected_language = "en"
            
            # For non-English messages, queue for background processing to avoid timeouts
            if detected_language != "en":
                reply_text = queue_text_processing(Body, thread_id, From, detected_language)
                
                # Return immediate acknowledgment
                twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
                <Response>
                    <Message>{html.escape(reply_text)}</Message>
                </Response>"""
            else:
                # Process English messages synchronously as before
                # Process through LangGraph with English text
                graph = app.state.graph
                from app.langgraph.graph_config import invoke_graph
                state = await invoke_graph(graph, english_text, thread_id, detected_language=detected_language)
                print("awaited invoke_graph done")
                reply_text = extract_last_ai_text(state) or "Got it."
                print(f"🤖 Assistant reply: {reply_text}")
                
                # Translate response back to detected language if needed
                if detected_language != "en":
                    translated_reply = await translation_service.translate_from_english(reply_text, detected_language)
                    print(f"Translated reply: {translated_reply}")
                    if translated_reply:
                        reply_text = translated_reply
                        print(f"reply text: {reply_text}")
                
                twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
                <Response>
                    <Message>{html.escape(reply_text)}</Message>
                </Response>"""
            
    except Exception as e:
        print(f"❌ Error processing message: {e}")
        reply_text = f"Error: {e}"
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Message>{html.escape(reply_text)}</Message>
        </Response>"""
    
    return Response(content=twiml, media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)

