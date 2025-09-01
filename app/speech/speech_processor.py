"""
Speech processing module using AssemblyAI (STT) and SpeechGen TTS
"""
import os
import tempfile
import urllib.parse
import time
from typing import Optional, Callable, Tuple, Dict, Any
import requests
import assemblyai as aai
from openai import OpenAI
import queue
import threading

# Global task queue for voice processing
_voice_task_queue = queue.Queue()
_voice_worker_thread = None
_voice_worker_running = False

# SpeechGen.io TTS Client
class SpeechGenClient:
    """Minimal SpeechGen.io TTS client for voice synthesis"""
    
    def __init__(self, token: str, email: str = "hummd2001@gmail.com"):
        if not token:
            raise ValueError("Missing SPEECHGEN_API_KEY environment variable")
        self.token = token
        self.email = email
        self.base_url = "https://speechgen.io/"
        self._session = requests.Session()
    
    def get_voices(self, langs: Optional[list] = None) -> Dict[str, Any]:
        """Get available voices, optionally filtered by languages"""
        url = urllib.parse.urljoin(self.base_url, "index.php?r=api/voices")
        params = {}
        if langs:
            params["langs"] = ",".join(langs)
        resp = self._session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    
    def tts_quick(self, voice: str, text: str, output_path: str) -> str:
        """Generate TTS audio file using quick API (<=2000 chars)"""
        if len(text) > 2000:
            raise ValueError("Text too long for quick TTS (max 2000 chars)")
        
        url = urllib.parse.urljoin(self.base_url, "index.php?r=api/text")
        payload = {
            "token": self.token,
            "email": self.email,
            "voice": voice,
            "text": text,
            "format": "mp3",
            "speed": 1.0,
            "pitch": 0,
            "emotion": "good",
        }
        
        # Submit TTS request
        resp = self._session.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        status = int(data.get("status", -1))
        if status == -1:
            raise RuntimeError(f"SpeechGen TTS failed: {data.get('error', 'unknown error')}")
        
        # Get file URL and download
        file_url = data.get("file") or data.get("file_cors")
        if not file_url:
            raise RuntimeError("No file URL returned from SpeechGen")
        
        # Download the audio file
        if not file_url.startswith("http"):
            file_url = urllib.parse.urljoin(self.base_url, file_url.lstrip("/"))
        
        with self._session.get(file_url, timeout=30) as r:
            r.raise_for_status()
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        
        return output_path

class SpeechProcessor:
    """Handles speech-to-text using AssemblyAI and text-to-speech operations using SpeechGen"""
    
    def __init__(self):
        # Initialize AssemblyAI for STT
        aai.settings.api_key = os.getenv('ASSEMBLYAI_API_KEY')
        if not os.getenv('ASSEMBLYAI_API_KEY'):
            print("⚠️ Warning: ASSEMBLYAI_API_KEY not found in environment variables")
        
        # Initialize SpeechGen for TTS
        speechgen_key = os.getenv('SPEECHGEN_API_KEY')
        if speechgen_key:
            self.speechgen_client = SpeechGenClient(speechgen_key)
            print("✅ SpeechGen TTS initialized")
        else:
            print("⚠️ Warning: SPEECHGEN_API_KEY not found in environment variables")
            self.speechgen_client = None
    
    def _get_voice_for_language(self, detected_language: str, fallback_voice: str = "John") -> str:
        """Select appropriate voice based on detected language"""
        if not self.speechgen_client:
            return fallback_voice
        
        try:
            # Map common language codes to SpeechGen format
            lang_map = {
                # --- English & variants ---
                "en": "en", "en_us": "en", "en_gb": "en", "en_uk": "en", "en_au": "en", "en_ca": "en",
                "en_in": "en", "en_ie": "en", "en_nz": "en", "en_ph": "en", "en_za": "en",

                # --- Romance languages ---
                "es": "es", "es_419": "es", "es_mx": "es", "es_es": "es", "es_ar": "es",
                "es_co": "es", "es_cl": "es", "es_pe": "es", "es_ve": "es", "es_uy": "es", "es_bo": "es",

                "pt": "pt", "pt_br": "pt", "pt_pt": "pt", "pt_mz": "pt",

                "fr": "fr", "fr_fr": "fr", "fr_ca": "fr", "fr_be": "fr", "fr_ch": "fr",

                "it": "it", "ro": "ro", "ro_ro": "ro",

                "ca": "ca", "gl": "gl",

                # --- Germanic languages ---
                "de": "de", "de_de": "de", "de_at": "de", "de_ch": "de",
                "nl": "nl", "nl_nl": "nl", "nl_be": "nl",
                "sv": "sv", "sv_se": "sv",
                "da": "da", "no": "no", "nb": "no", "nn": "no",
                "is": "is",

                # --- Slavic & Baltic ---
                "pl": "pl", "cs": "cs", "sk": "sk", "sl": "sl",
                "hr": "hr", "sr": "sr", "sr_rs": "sr", "sr_latn": "sr", "sr_cyrl": "sr",
                "bs": "bs", "bg": "bg", "mk": "mk",
                "ru": "ru", "ru_ru": "ru", "uk": "uk", "be": "be",
                "lv": "lv", "lt": "lt", "et": "et",

                # --- Greek, Turkish, Caucasus, Central Asia ---
                "el": "el", "el_gr": "el",
                "tr": "tr", "hy": "hy", "ka": "ka",
                "az": "az", "kk": "kk", "ky": "ky", "uz": "uz", "tk": "tk",

                # --- Semitic & Iranian ---
                "he": "he", "iw": "he",  # legacy 'iw' -> Hebrew
                "ar": "ar", "ar_eg": "ar", "ar_sa": "ar", "ar_ae": "ar", "ar_ma": "ar",
                "ar_lb": "ar", "ar_sy": "ar", "ar_iq": "ar", "ar_dz": "ar", "ar_jo": "ar",
                "ar_kw": "ar", "ar_om": "ar", "ar_qa": "ar", "ar_bh": "ar", "ar_ye": "ar",
                "ar_ly": "ar", "ar_tn": "ar", "ar_ps": "ar", "ar_sd": "ar",

                "fa": "fa", "fa_ir": "fa", "fa_af": "fa", "prs": "fa",  # Dari -> fa
                "kur": "ku", "ku": "ku", "ckb": "ku",  # Sorani -> Kurdish generic
                "ps": "ps",  # Pashto

                # --- South Asian (India, Pakistan, etc.) ---
                "hi": "hi", "hi_in": "hi",
                "bn": "bn", "bn_bd": "bn", "bn_in": "bn",
                "gu": "gu", "gu_in": "gu",
                "pa": "pa", "pa_in": "pa", "pa_pk": "pa", "pa_guru": "pa", "pa_arab": "pa",
                "mr": "mr", "ne": "ne", "si": "si",
                "ta": "ta", "ta_in": "ta", "ta_lk": "ta",
                "te": "te", "kn": "kn", "ml": "ml",
                "as": "as", "or": "or", "sa": "sa",
                "ur": "ur", "ur_pk": "ur", "ur_in": "ur",

                # --- SE Asia ---
                "th": "th", "lo": "lo", "km": "km", "my": "my", "vi": "vi",
                "id": "id", "ms": "ms", "jv": "jv", "su": "su",
                "tl": "tl", "fil": "tl",

                # --- East Asia ---
                "zh": "zh", "zh_cn": "zh", "zh_sg": "zh", "zh_tw": "zh", "zh_hk": "zh",
                "zh_hans": "zh", "zh_hant": "zh", "cmn": "zh", "yue": "zh",  # Mandarin/Cantonese -> zh
                "ja": "ja", "ko": "ko", "mn": "mn",

                # --- Africa (commonly encountered) ---
                "am": "am", "ti": "ti", "so": "so",
                "sw": "sw", "sw_ke": "sw", "sw_tz": "sw",
                "ha": "ha", "ig": "ig", "yo": "yo",
                "zu": "zu", "xh": "xh", "st": "st", "tn": "tn", "ts": "ts",
                "rw": "rw", "mg": "mg", "af": "af",

                # --- Others / constructed / regional ---
                "sq": "sq", "eo": "eo", "eu": "eu", "ga": "ga", "mt": "mt", "cy": "cy",
                "glg": "gl", "cat": "ca", "la": "la", "bo": "bo", "ug": "ug",
            }
            
            lang = lang_map.get(detected_language, 'en')
            print(f"🗣️ Getting voices for language: {lang}")
            
            # Special handling for Urdu - always use Uzma
            if lang == 'ur':
                print(f"🗣️ Selected voice: Uzma for language: {lang} (hardcoded)")
                return "Uzma"
            
            data = self.speechgen_client.get_voices(langs=[lang])
            
            # Handle different response structures
            voices = []
            if isinstance(data, dict):
                # Check if it's the nested structure like {"Urdu (Pakistan)": [...]}
                for key, value in data.items():
                    if isinstance(value, list):
                        voices.extend(value)
                
                # If no nested structure found, try the direct structure
                if not voices:
                    voices = data.get("voices", [])
            elif isinstance(data, list):
                voices = data
            
            if voices and len(voices) > 0:
                # Get the first available voice for the language
                v = voices[0]
                voice_name = v.get("voice") or v.get("title") or v.get("name") or fallback_voice
                print(f"🗣️ Selected voice: {voice_name} for language: {lang}")
                return voice_name
            else:
                print(f"⚠️ No voices found for language {lang}, using fallback: {fallback_voice}")
                return fallback_voice
                
        except Exception as e:
            print(f"⚠️ Error selecting voice for language {detected_language}: {e}")
            return fallback_voice
    
    def speech_to_text_direct(self, audio_url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Convert speech to text using AssemblyAI with language detection
        
        Args:
            audio_url: URL of the audio file to transcribe (supports Twilio authenticated URLs)
            
        Returns:
            Tuple of (transcribed_text, detected_language_code) or (None, None) if error
        """
        try:
            print(f"🎤 Transcribing audio with AssemblyAI and language detection...")
            
            # Check if this is a Twilio URL that needs S3 proxy
            transcription_url = audio_url
            if "twilio.com" in audio_url:
                print(f"🔗 Detected Twilio URL, using S3 proxy...")
                from app.services.s3_handler import secure_tazaticket_s3
                
                # Extract user ID from audio URL (use a simple hash if not available)
                import hashlib
                user_id = hashlib.md5(audio_url.encode()).hexdigest()[:8]
                
                # Upload to S3 and get public URL
                public_url = secure_tazaticket_s3.upload_from_twilio_url(audio_url, user_id)
                if not public_url:
                    print(f"❌ Failed to upload Twilio media to S3")
                    return None, None
                
                transcription_url = public_url
                print(f"✅ Using S3 presigned URL for AssemblyAI: {transcription_url[:50]}...")
            
            # Configure AssemblyAI transcription with language detection
            config = aai.TranscriptionConfig(language_detection=True)
            transcript = aai.Transcriber(config=config).transcribe(transcription_url)
            
            if transcript.status == "error":
                print(f"❌ AssemblyAI transcription failed: {transcript.error}")
                return None, None
            
            transcribed_text = transcript.text
            detected_language = transcript.json_response.get("language_code", "en")
            
            print(f"🎤 STT successful: {transcribed_text[:50]}...")
            print(f"🌍 Detected language: {detected_language}")
            
            return transcribed_text, detected_language
                
        except Exception as e:
            print(f"❌ STT error: {e}")
            return None, None
    
    def text_to_speech(self, text: str, detected_language: str = "en") -> Optional[str]:
        """
        Convert text to speech using SpeechGen TTS with automatic voice selection
        
        Args:
            text: Text to convert to speech
            detected_language: Language code to select appropriate voice
            
        Returns:
            Path to the generated audio file or None if error
        """
        if not self.speechgen_client:
            print("❌ SpeechGen client not configured")
            return None
            
        try:
            # Select appropriate voice for the detected language
            voice = self._get_voice_for_language(detected_language)
            
            # Create temporary file for the audio
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            temp_file.close()
            
            # Generate speech using SpeechGen
            output_path = self.speechgen_client.tts_quick(voice, text, temp_file.name)
            
            print(f"🔊 SpeechGen TTS successful: {text[:50]}... (voice: {voice})")
            return output_path
            
        except Exception as e:
            print(f"❌ SpeechGen TTS error: {e}")
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
        
        # Step 1: Convert voice to text with language detection using AssemblyAI
        transcribed_text, detected_language = speech_processor.speech_to_text_direct(media_url)
        
        if not transcribed_text:
            send_twilio_message(from_number, "Sorry, I couldn't understand the voice message.")
            return
        
        # Step 2: Translate to English if needed (detected_language already from AssemblyAI)
        english_text = transcribed_text
        if detected_language != "en":
            from app.services.translation_service import translation_service
            _, translated_text = translation_service.detect_and_translate_to_english(transcribed_text)
            if translated_text:
                english_text = translated_text
                print(f"[VoiceProcessor] Translated to English: '{english_text[:50]}...'")
            else:
                print(f"[VoiceProcessor] Translation failed, using original text")
        
        print(f"[VoiceProcessor] Language: {detected_language}, Processing text: '{english_text[:50]}...'")
        
        # Step 3: Process through LangGraph with English text
        from app.langgraph import create_graph, invoke_graph, extract_last_ai_text
        graph = create_graph()
        state = invoke_graph(graph, english_text, thread_id, is_voice=True, detected_language=detected_language)
        reply_text = extract_last_ai_text(state) or "Got it."
        
        # Step 4: Translate response back to detected language if needed
        if detected_language != "en":
            from app.services.translation_service import translation_service
            translated_reply = translation_service.translate_from_english(reply_text, detected_language)
            if translated_reply:
                reply_text = translated_reply
                print(f"[VoiceProcessor] Translated response to {detected_language}: '{reply_text[:50]}...'")
        
        # Step 5: Convert to speech (minimal local storage)
        audio_file_path = speech_processor.text_to_speech(reply_text, detected_language)
        if not audio_file_path:
            # Fallback to text if TTS fails
            send_twilio_message(from_number, reply_text)
            return
        
        # Step 6: Upload to S3
        from app.services.s3_handler import secure_tazaticket_s3
        presigned_url = secure_tazaticket_s3.upload_voice_file(audio_file_path, thread_id)
        
        # Clean up local file
        if os.path.exists(audio_file_path):
            os.unlink(audio_file_path)
        
        # Step 7: Send voice response
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