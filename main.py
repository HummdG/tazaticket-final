import os 
from dotenv import load_dotenv
import html

from fastapi import FastAPI, Form
from fastapi.responses import Response

# Import our LangGraph configuration
from app.langgraph import create_graph, invoke_graph, extract_last_ai_text

# Import voice processing components
from app.speech.speech_processor import queue_voice_task, process_voice_message_background

# Create the graph
graph = create_graph()

# Create FastAPI app
app = FastAPI()

@app.get("/")
async def healthcheck():
    return {"status": "ok"}

def queue_voice_processing(media_url: str, thread_id: str, from_number: str) -> str:
    """Queue voice message for background processing and return immediate response"""
    try:
        print(f"🎤 Queueing voice message for background processing: {media_url}")
        
        # Queue the heavy processing for background
        queue_voice_task(process_voice_message_background, media_url, thread_id, from_number)
        
        return "🎤 Got your voice message! We're working on it and will respond shortly..."
        
    except Exception as e:
        print(f"❌ Error queueing voice processing: {e}")
        return "Sorry, there was an error processing your voice message."

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
            from app.services.translation_service import translation_service
            detected_language, english_text = translation_service.detect_and_translate_to_english(Body)
            
            if english_text is None:
                # Translation failed, use original text
                english_text = Body
                detected_language = "en"
            
            # Process through LangGraph with English text
            state = invoke_graph(graph, english_text, thread_id, detected_language=detected_language)
            reply_text = extract_last_ai_text(state) or "Got it."
            
            # Translate response back to detected language if needed
            if detected_language != "en":
                translated_reply = translation_service.translate_from_english(reply_text, detected_language)
                if translated_reply:
                    reply_text = translated_reply
            
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Message>{html.escape(reply_text)}</Message>
            </Response>"""
            
    except Exception as e:
        reply_text = f"Error: {e}"
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Message>{html.escape(reply_text)}</Message>
        </Response>"""
    
    return Response(content=twiml, media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)

