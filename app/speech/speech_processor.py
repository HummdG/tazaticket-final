"""
Speech processing module using AssemblyAI (STT) and SpeechGen TTS
"""
import os
import tempfile
import urllib.parse
import time
from typing import Optional, Callable, Tuple, Dict, Any
import httpx
import requests
import assemblyai as aai
from openai import OpenAI
import queue
import threading


def _normalize_lang_code(code: str) -> str:
    """
    Normalize a detected language code to a canonical 'll' or 'll_rr' form
    compatible with our VOICE_MAP keys.
    Examples:
      'en', 'en-US', 'en_us', 'EN-gb' -> 'en'
      'es-419' -> 'es_419'
      'pa-IN' -> 'pa_in'
      'pa-PK' -> 'pa_pk'
      'zh-Hant' -> 'zh_hant'
      'yue' -> 'yue' (Cantonese)
    """
    if not code:
        return "en"
    c = code.strip().replace("-", "_").lower()
    # Some providers use legacy tags
    legacy = {
        "iw": "he",       # Hebrew
        "prs": "fa",      # Dari
        "cmn": "zh",      # Mandarin treated as zh
    }
    c = legacy.get(c, c)

    # Common country aliases -> regioned forms
    region_alias = {
        "en_gb": "en", "en_uk": "en", "en_us": "en", "en_au": "en", "en_ca": "en",
        "en_ie": "en", "en_nz": "en", "en_ph": "en", "en_za": "en",
        "es_es": "es", "es_mx": "es", "es_ar": "es", "es_co": "es", "es_cl": "es",
        "es_pe": "es", "es_ve": "es", "es_uy": "es", "es_bo": "es",
        "pt_pt": "pt", "pt_br": "pt",
        "fr_fr": "fr", "fr_ca": "fr", "fr_be": "fr", "fr_ch": "fr",
        "ru_ru": "ru",
        "zh_cn": "zh", "zh_sg": "zh",
        # Keep specific ones we care about distinct
        "zh_tw": "zh_tw",
        "zh_hk": "zh_hk",
        "es_419": "es_419",
        "zh_hans": "zh_hans",
        "zh_hant": "zh_hant",
        "pa_in": "pa_in",
        "pa_pk": "pa_pk",
    }
    c = region_alias.get(c, c)

    # If it has script subtags like zh_Hant_TW → prefer script when useful
    parts = c.split("_")
    if parts[0] == "zh":
        # Cantonese special cases
        if "yue" in parts or c == "yue":
            return "yue"
        if "hk" in parts:
            return "zh_hk"
        if "tw" in parts:
            return "zh_tw"
        if "hant" in parts:
            return "zh_hant"
        if "hans" in parts:
            return "zh_hans"
        return "zh"

    return c

# Canonical language-code → exact SpeechGen voice names (from your list)
VOICE_MAP = {
    # English (defaulting all en* to Amelia)
    "en": "Amelia",

    # Africa / Middle East / Asia
    "af": "Adri",                 # Afrikaans
    "sq": "Anila",                # Albanian
    "am": "Mekdes",               # Amharic
    "ar": "Farida",               # Arabic
    "hy": "Anahit",               # Armenian
    "az": "Banu",                 # Azerbaijani
    "eu": "Ainhoa",               # Basque
    "bn": "Nabanita",             # Bengali
    "bs": "Vesna",                # Bosnian
    "bg": "Kalina",               # Bulgarian
    "my": "Nilar",                # Burmese
    "ca": "Alba",                 # Catalan
    "zh": "Zhiyu plus",           # Chinese (Mandarin generic)
    "zh_hans": "Zhiyu plus",
    "zh_hant": "Zhiyu plus",
    "zh_tw": "Zhiyu plus",
    "zh_hk": "HiuGaai",           # if Hong Kong, prefer Cantonese voice
    "yue": "HiuGaai",             # Cantonese
    "hr": "Gabrijela",            # Croatian
    "cs": "Jitka plus",           # Czech
    "da": "Leonora",              # Danish
    "nl_be": "Dena",              # Dutch (Belgian)
    "et": "Anu",                  # Estonian
    "fil": "Amihan", "tl": "Amihan",  # Filipino
    "fi": "Suvi plus",            # Finnish
    "fr": "Abelin",               # French
    "gl": "Sabela",               # Galician
    "ka": "Eka",                  # Georgian
    "de": "Angelika",             # German
    "el": "Ophelia",              # Greek
    "gu": "Dhwani",               # Gujarati
    "he": "Miriam",               # Hebrew
    "hi": "Swara",                # Hindi
    "hu": "Noemi",                # Hungarian
    "is": "Gudrun",               # Icelandic
    "id": "Dzhu",                 # Indonesian
    "ga": "Orla",                 # Irish
    "it": "Bianca plus",          # Italian
    "ja": "Aoi",                  # Japanese
    "jv": "Siti",                 # Javanese
    "kn": "Sapna",                # Kannada
    "kk": "Aigul",                # Kazakh
    "km": "Sreymom",              # Khmer
    "ko": "Jihye plus",           # Korean
    "lo": "Keomany",              # Lao
    "lv": "Everita",              # Latvian
    "lt": "Ona",                  # Lithuanian
    "mk": "Marija",               # Macedonian
    "ms": "Yasmin",               # Malay
    "ml": "Sobhana",              # Malayalam
    "mt": "Ganni",                # Maltese
    "mr": "Aarohi",               # Marathi
    "mn": "Yesui",                # Mongolian
    "ne": "Hemkala",              # Nepali
    "no": "Ida plus", "nb": "Ida plus", "nn": "Ida plus",  # Norwegian
    "ps": "Latifa",               # Pashto
    "fa": "Dilara",               # Persian/Farsi
    "pl": "Ola plus",             # Polish
    "pt": "Ines plus",            # Portuguese
    "pa_in": "Gurpreet",          # Punjabi (India, Gurmukhi)
    "pa_pk": "Uzma",              # Punjabi (Pakistan, Shahmukhi via Urdu)
    "pa": "Gurpreet",             # Default Punjabi -> Indian voice unless specified
    "ro": "Anisa",                # Romanian
    "ru": "Elena",                # Russian
    "sr": "Sophie",               # Serbian
    "si": "Thilini",              # Sinhala
    "sk": "Viktoria",             # Slovak
    "sl": "Petra",                # Slovenian
    "so": "Ubax",                 # Somali
    "es": "Abril",                # Spanish
    "su": "Tuti",                 # Sundanese
    "sw": "Zuri",                 # Swahili
    "sv": "Elin plus",            # Swedish
    "ta": "Pallavi",              # Tamil
    "te": "Shruti",               # Telugu
    "th": "Achara",               # Thai
    "tr": "Chilek",               # Turkish
    "uk": "Uliana",               # Ukrainian
    "ur": "Uzma",                 # Urdu
    "uz": "Madina",               # Uzbek
    "vi": "Linh",                 # Vietnamese
    "zu": "Thando",               # Zulu
}


# Global task queue for voice processing
# TD: redis based queue
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
        # TD: async client using httpx
        # TD: - Implement connection pooling for HTTP requests using httpx.AsyncClient with connection limits
        self._session = httpx.AsyncClient()

    async def get_voices(self, langs: Optional[list] = None) -> Dict[str, Any]:
        """Get available voices, optionally filtered by languages"""
        url = urllib.parse.urljoin(self.base_url, "index.php?r=api/voices")
        params = {}
        if langs:
            params["langs"] = ",".join(langs)
        # Done: async await call
        resp = await self._session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    async def tts_quick(self, voice: str, text: str, output_path: str) -> str:
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
        # TD: async await call
        # TD: - Implement connection pooling for HTTP requests using httpx.AsyncClient with connection limits
        async with self._session.post(url, data=payload, timeout=30) as resp:
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
        
        # TD: async await call
        async with self._session.get(file_url, timeout=30) as r:
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
        # TD: async client if available 
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
        """
        Pick a SpeechGen voice deterministically from detected language code,
        with a final fallback to API probing if unrecognized.
        """
        if not self.speechgen_client:
            return fallback_voice

        try:
            lang_norm = _normalize_lang_code(detected_language)
            # 1) Direct map: fastest and deterministic
            mapped = VOICE_MAP.get(lang_norm)
            if mapped:
                print(f"🗣️ Selected mapped voice '{mapped}' for language '{lang_norm}' (raw: '{detected_language}')")
                return mapped

            # 2) Try collapsing to base language (e.g., 'es_419' -> 'es')
            base = lang_norm.split("_")[0]
            if base in VOICE_MAP:
                print(f"🗣️ Selected base voice '{VOICE_MAP[base]}' for language '{lang_norm}' (raw: '{detected_language}')")
                return VOICE_MAP[base]

            # 3) As a last resort, ask SpeechGen which voices exist for the base
            print(f"🗣️ Unknown code '{detected_language}' → probing SpeechGen for base '{base}'")
            data = self.speechgen_client.get_voices(langs=[base])
            voices = []
            if isinstance(data, dict):
                for _, value in data.items():
                    if isinstance(value, list):
                        voices.extend(value)
                if not voices:
                    voices = data.get("voices", [])
            elif isinstance(data, list):
                voices = data

            if voices:
                v = voices[0]
                voice_name = v.get("voice") or v.get("title") or v.get("name") or fallback_voice
                print(f"🗣️ Selected probed voice '{voice_name}' for base '{base}'")
                return voice_name

            print(f"⚠️ No voices found via API for '{base}', using fallback '{fallback_voice}'")
            return fallback_voice

        except Exception as e:
            print(f"⚠️ Error selecting voice for language '{detected_language}': {e}")
            return fallback_voice
    # TD: async await
    async def speech_to_text_direct(self, audio_url: str) -> Tuple[Optional[str], Optional[str]]:
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
            # TD: async await
            config = aai.TranscriptionConfig(language_detection=True)
            transcript = await aai.Transcriber(config=config).transcribe(transcription_url)

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
            tts_text = text
            tts_language = detected_language
            
            # Special handling for Punjabi: translate English text to pa-Arab and use Urdu voice
            if detected_language == "pa" or detected_language == "pa_in" or detected_language == "pa_pk":
                print(f"🌍 Detected Punjabi language, translating English text to Shahmukhi script")
                from app.services.translation_service import translation_service
                
                translated_text = translation_service.translate_en_to_shahmukhi(text)
                if translated_text:
                    tts_text = translated_text
                    tts_language = "ur"  # Use Urdu voice for Punjabi Shahmukhi
                    print(f"🔄 Using Punjabi (Shahmukhi) text with Urdu voice: '{tts_text[:50]}...'")
                else:
                    print(f"⚠️ Failed to translate to Shahmukhi, using original text with Urdu voice")
                    tts_language = "ur"  # Still use Urdu voice as fallback
            
            # Select appropriate voice for the TTS language
            voice = self._get_voice_for_language(tts_language)
            
            # Create temporary file for the audio
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            temp_file.close()
            
            # Generate speech using SpeechGen
            output_path = self.speechgen_client.tts_quick(voice, tts_text, temp_file.name)
            
            print(f"🔊 SpeechGen TTS successful: {tts_text[:50]}... (voice: {voice})")
            return output_path
            
        except Exception as e:
            print(f"❌ SpeechGen TTS error: {e}")
            return None
    
    def is_configured(self) -> bool:
        """Check if OpenAI API key is configured"""
        return bool(os.getenv('OPENAI_API_KEY'))

# TD: async task processing
async def _voice_worker():
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
            
            # Special handling for Punjabi - don't translate the response here
            # The TTS pipeline will handle English->Shahmukhi translation
            if detected_language not in ["pa", "pa_in", "pa_pk"]:
                translated_reply = translation_service.translate_from_english(reply_text, detected_language)
                if translated_reply:
                    reply_text = translated_reply
                    print(f"[VoiceProcessor] Translated response to {detected_language}: '{reply_text[:50]}...'")
            else:
                print(f"[VoiceProcessor] Keeping English response for Punjabi TTS pipeline: '{reply_text[:50]}...'")
        
        # Step 5: Convert to speech (minimal local storage)
        # For Punjabi, pass the English text - TTS pipeline will handle translation
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

async def send_twilio_message(to_number: str, message: str):
    """Send a text message via Twilio"""
    try:
        from twilio.rest import Client
        
        account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        from_number = os.getenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')
        
        if not all([account_sid, auth_token]):
            print("❌ Twilio credentials missing for message sending")
            return
        # TD: async client 
        client = Client(account_sid, auth_token)
        # TD: async await
        message = await client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        print(f"✅ Sent text message: {message.sid}")
        
    except Exception as e:
        print(f"❌ Error sending Twilio message: {e}")

async def send_twilio_voice_message(to_number: str, media_url: str):
    """Send a voice message via Twilio"""
    try:
        from twilio.rest import Client
        
        account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        from_number = os.getenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')
        
        if not all([account_sid, auth_token]):
            print("❌ Twilio credentials missing for voice message sending")
            return
        # TD: async client
        client = Client(account_sid, auth_token)
        # TD: async await
        message = await client.messages.create(
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