"""
Speech processing module using OpenAI's Whisper (STT) and TTS
"""
import os
import tempfile
from typing import Optional, Callable
import requests
from openai import OpenAI
import queue
import threading

# Global task queue for voice processing
_voice_task_queue = queue.Queue()
_voice_worker_thread = None
_voice_worker_running = False

class SpeechProcessor:
    """Handles speech-to-text and text-to-speech operations using OpenAI"""
    
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        if not os.getenv('OPENAI_API_KEY'):
            print("⚠️ Warning: OPENAI_API_KEY not found in environment variables")
    
    def speech_to_text_direct(self, audio_url: str) -> Optional[str]:
        """
        Convert speech to text using OpenAI Whisper (direct upload without local storage)
        
        Args:
            audio_url: URL of the audio file to transcribe (supports Twilio authenticated URLs)
            
        Returns:
            Transcribed text or None if error
        """
        try:
            # For Twilio URLs, we need to authenticate with Account SID and Auth Token
            if "twilio.com" in audio_url:
                # Get Twilio credentials from environment
                account_sid = os.getenv('TWILIO_ACCOUNT_SID')
                auth_token = os.getenv('TWILIO_AUTH_TOKEN')
                
                if not account_sid or not auth_token:
                    print("❌ Twilio credentials not found in environment variables")
                    return None
                
                print(f"🔐 Streaming Twilio audio for transcription...")
                # Stream download with Basic Auth for Twilio
                response = requests.get(
                    audio_url, 
                    auth=(account_sid, auth_token),
                    timeout=30,
                    stream=True
                )
            else:
                # Stream download without auth for non-Twilio URLs
                response = requests.get(audio_url, timeout=30, stream=True)
            
            response.raise_for_status()
            
            print(f"🎤 Transcribing audio directly from stream...")
            
            # Transcribe directly from response content without saving to disk
            import io
            audio_file = io.BytesIO(response.content)
            audio_file.name = "audio.ogg"  # OpenAI needs a filename
            
            transcript = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
            
            print(f"🎤 STT successful: {transcript[:50]}...")
            return transcript
                
        except requests.RequestException as e:
            print(f"❌ Error downloading audio: {e}")
            return None
        except Exception as e:
            print(f"❌ STT error: {e}")
            return None
    
    def text_to_speech(self, text: str, voice: str = "alloy") -> Optional[str]:
        """
        Convert text to speech using OpenAI TTS
        
        Args:
            text: Text to convert to speech
            voice: Voice to use (alloy, echo, fable, onyx, nova, shimmer)
            
        Returns:
            Path to the generated audio file or None if error
        """
        try:
            # Generate speech
            response = self.client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text
            )
            
            # Create temporary file for the audio
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            temp_file.write(response.content)
            temp_file.close()
            
            print(f"🔊 TTS successful: {text[:50]}...")
            return temp_file.name
            
        except Exception as e:
            print(f"❌ TTS error: {e}")
            return None
    
    def is_configured(self) -> bool:
        """Check if OpenAI API key is configured"""
        return bool(os.getenv('OPENAI_API_KEY'))

def _voice_worker():
    """Background worker that processes voice tasks"""
    global _voice_worker_running
    _voice_worker_running = True
    print("[VoiceProcessor] Background worker started")
    
    while _voice_worker_running:
        try:
            task = _voice_task_queue.get(timeout=1.0)
            if task is None:  # Shutdown signal
                break
            
            task_func, args, kwargs = task
            print(f"[VoiceProcessor] Processing task: {task_func.__name__}")
            task_func(*args, **kwargs)
            _voice_task_queue.task_done()
            
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[VoiceProcessor] Error in background worker: {e}")
    
    _voice_worker_running = False
    print("[VoiceProcessor] Background worker stopped")

def start_voice_worker():
    """Start the background voice processing worker"""
    global _voice_worker_thread, _voice_worker_running
    
    if _voice_worker_running:
        return
    
    _voice_worker_thread = threading.Thread(target=_voice_worker, daemon=True)
    _voice_worker_thread.start()
    print("[VoiceProcessor] Background worker thread started")

def queue_voice_task(task_func: Callable, *args, **kwargs):
    """Add a voice processing task to the background queue"""
    if not _voice_worker_running:
        start_voice_worker()
    
    print(f"[VoiceProcessor] Queueing voice task")
    _voice_task_queue.put((task_func, args, kwargs))

def process_voice_message_background(media_url: str, thread_id: str, from_number: str):
    """
    Process voice message in background and send result via Twilio
    This function runs in a separate thread.
    """
    try:
        print(f"[VoiceProcessor] Starting background processing for {thread_id}")
        
        # Step 1: Convert voice to text
        transcribed_text = speech_processor.speech_to_text_direct(media_url)
        
        if not transcribed_text:
            send_twilio_message(from_number, "Sorry, I couldn't understand the voice message.")
            return
        
        # Step 2: Process through LangGraph
        from app.langgraph import create_graph, invoke_graph, extract_last_ai_text
        graph = create_graph()
        state = invoke_graph(graph, transcribed_text, thread_id, is_voice=True)
        reply_text = extract_last_ai_text(state) or "Got it."
        
        # Step 3: Convert to speech (minimal local storage)
        audio_file_path = speech_processor.text_to_speech(reply_text)
        if not audio_file_path:
            # Fallback to text if TTS fails
            send_twilio_message(from_number, reply_text)
            return
        
        # Step 4: Upload to S3
        from app.services.s3_handler import secure_tazaticket_s3
        presigned_url = secure_tazaticket_s3.upload_voice_file(audio_file_path, thread_id)
        
        # Clean up local file
        if os.path.exists(audio_file_path):
            os.unlink(audio_file_path)
        
        # Step 5: Send voice response
        if presigned_url:
            send_twilio_voice_message(from_number, presigned_url)
        else:
            # Fallback to text
            send_twilio_message(from_number, reply_text)
            
    except Exception as e:
        print(f"[VoiceProcessor] Background processing error: {e}")
        send_twilio_message(from_number, "Sorry, there was an error processing your voice message.")

def send_twilio_message(to_number: str, message: str):
    """Send a text message via Twilio"""
    try:
        from twilio.rest import Client
        
        account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        from_number = os.getenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')
        
        if not all([account_sid, auth_token]):
            print("❌ Twilio credentials missing for message sending")
            return
        
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        print(f"✅ Sent text message: {message.sid}")
        
    except Exception as e:
        print(f"❌ Error sending Twilio message: {e}")

def send_twilio_voice_message(to_number: str, media_url: str):
    """Send a voice message via Twilio"""
    try:
        from twilio.rest import Client
        
        account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        from_number = os.getenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')
        
        if not all([account_sid, auth_token]):
            print("❌ Twilio credentials missing for voice message sending")
            return
        
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            media_url=[media_url],
            from_=from_number,
            to=to_number
        )
        print(f"✅ Sent voice message: {message.sid}")
        
    except Exception as e:
        print(f"❌ Error sending Twilio voice message: {e}")

# Global speech processor instance
speech_processor = SpeechProcessor()

# Start the background worker when module is imported
start_voice_worker() 