"""
Speech processing module — async-first, httpx pooled clients, AssemblyAI REST polling,
SpeechGen async calls, Twilio via HTTP (async), and an asyncio background worker thread.
"""

import os
import tempfile
import urllib.parse
import time
import asyncio
import inspect
import functools
import threading
import queue
import tempfile
from typing import Optional, Callable, Tuple, Dict, Any

import httpx

# ---------- Configuration for pooling / timeouts ----------
_HTTPX_MAX_CONNECTIONS = int(os.getenv("HTTPX_MAX_CONNECTIONS", "60"))
_HTTPX_MAX_KEEPALIVE = int(os.getenv("HTTPX_MAX_KEEPALIVE", "20"))
_HTTPX_TIMEOUT = float(os.getenv("HTTPX_TIMEOUT_SEC", "30.0"))
_ASSEMBLYAI_POLL_TIMEOUT = int(os.getenv("ASSEMBLYAI_POLL_TIMEOUT", "180"))  # seconds

# ---------- Lazy singleton async http client with pooling ----------
_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        limits = httpx.Limits(
            max_connections=_HTTPX_MAX_CONNECTIONS,
            max_keepalive_connections=_HTTPX_MAX_KEEPALIVE,
        )
        _http_client = httpx.AsyncClient(timeout=_HTTPX_TIMEOUT, limits=limits)
    return _http_client


# ---------- Language normalization & voice map (unchanged) ----------
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
import redis.asyncio as redis_async

# Redis connection for voice task queue
_redis_queue = None

_voice_task_queue = queue.Queue()
_voice_worker_thread = None
_voice_worker_running = False

# SpeechGen.io TTS Client
class SpeechGenClient:
    """Minimal SpeechGen.io TTS client for voice synthesis (async httpx)"""

    def __init__(self, token: str, email: str = "hummd2001@gmail.com", http_client: httpx.AsyncClient = None):
        if not token:
            raise ValueError("Missing SPEECHGEN_API_KEY environment variable")
        self.token = token
        self.email = email
        self.base_url = "https://speechgen.io/"
        # Done: async client with session
        # Done: - Implement connection pooling for HTTP requests using httpx.AsyncClient with connection limits
        self._session = http_client or get_http_client()

    async def get_voices(self, langs: Optional[list] = None) -> Dict[str, Any]:
        """Get available voices, optionally filtered by languages"""
        url = urllib.parse.urljoin(self.base_url, "index.php?r=api/voices")
        params = {}
        if langs:
            params["langs"] = ",".join(langs)
        # Done: async await call
        resp = await self._session.get(url, params=params)
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
        # Done: async await call
        # Done: - Implement connection pooling for HTTP requests using httpx.AsyncClient with connection limits
        # Doubt
        resp = await self._session.post(url, data=payload, timeout=_HTTPX_TIMEOUT)
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

        # Done: async await call
        # Download the audio file (async)

        async with self._session.stream("GET", file_url, timeout=_HTTPX_TIMEOUT) as r:
            r.raise_for_status()
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            # collect bytes then write in a threaded file write to avoid blocking the loop
            content = await r.aread()
            await asyncio.to_thread(_atomic_write_bytes, output_path, content)

        return output_path


def _atomic_write_bytes(path: str, content: bytes) -> None:
    with open(path, "wb") as f:
        f.write(content)


# ---------- Speech Processor ----------
class SpeechProcessor:
    """Handles STT (AssemblyAI) and TTS (SpeechGen) — async-first with sync wrappers"""

    def __init__(self):
        # Initialize AssemblyAI for STT
        # Done: async client if available 
        self.assembly_api_key = os.getenv("ASSEMBLYAI_API_KEY")
        if not self.assembly_api_key:
            print("! Warning: ASSEMBLYAI_API_KEY not found in environment variables")

# Initialize SpeechGen for TTS
        speechgen_key = os.getenv("SPEECHGEN_API_KEY")
        http_client = get_http_client()
        if speechgen_key:
            self.speechgen_client = SpeechGenClient(speechgen_key, http_client=http_client)
            print("+ SpeechGen TTS initialized (async httpx)")
        else:
            print("! Warning: SPEECHGEN_API_KEY not found in environment variables")
            self.speechgen_client = None

    # ---- Voice selection (async) ----
    async def _get_voice_for_language_async(self, detected_language: str, fallback_voice: str = "John") -> str:
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
                print(f"🗣️ Selected base voice '{VOICE_MAP[base]}' for language '{lang_norm}'")
                return VOICE_MAP[base]

            # 3) As a last resort, ask SpeechGen which voices exist for the base
            print(f"🗣️ Unknown code '{detected_language}' → probing SpeechGen for base '{base}'")
            data = await self.speechgen_client.get_voices(langs=[base])
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

    # ---- AssemblyAI transcription (async) ----
    # Done: async await
    async def speech_to_text_direct(self, audio_url: str, thread_id: str = "unknown") -> Tuple[Optional[str], Optional[str]]:
        """
        Async STT using AssemblyAI REST API with language_detection=True.
        Returns (text, language_code) or (None, None) on error.
        """
        if not self.assembly_api_key:
            print(f"❌ AssemblyAI API key not configured for thread {thread_id}")
            return None, None

        try:
            transcription_url = audio_url
            if "twilio.com" in audio_url:
                # Upload Twilio media to S3 via existing helper (sync) — run in thread
                from app.services.s3_handler import secure_tazaticket_s3
                import hashlib
                user_id = hashlib.md5(audio_url.encode()).hexdigest()[:8]
                # Upload to S3 and get public URL
                print(f"[STT] Uploading Twilio media to S3 for thread {thread_id}")
                public_url = await secure_tazaticket_s3.upload_from_twilio_url(audio_url, user_id)
                if not public_url:
                    print(f"❌ Failed to upload Twilio media to S3 for thread {thread_id}")
                    return None, None
                transcription_url = public_url
                print(f"[STT] Using S3 URL for AssemblyAI for thread {thread_id}: {transcription_url[:80]}...")
            # Configure AssemblyAI transcription with language detection
            # Done: async await
            client = get_http_client()
            endpoint = "https://api.assemblyai.com/v2/transcript"
            headers = {"authorization": self.assembly_api_key, "content-type": "application/json"}
            post_payload = {"audio_url": transcription_url, "language_detection": True}

            print(f"[STT] Starting AssemblyAI transcription for thread {thread_id}")
            post_resp = await client.post(endpoint, json=post_payload, headers=headers)
            post_resp.raise_for_status()
            post_data = post_resp.json()
            transcript_id = post_data.get("id")
            if not transcript_id:
                print(f"❌ No transcript id returned by AssemblyAI for thread {thread_id}")
                return None, None

            # Polling for completion with backoff
            poll_url = f"{endpoint}/{transcript_id}"
            start = time.time()
            interval = 0.7
            print(f"[STT] Started polling for transcription completion for thread {thread_id}")
            while True:
                get_resp = await client.get(poll_url, headers=headers)
                get_resp.raise_for_status()
                data = get_resp.json()
                status = data.get("status")
                if status == "completed":
                    text = data.get("text", "")
                    lang = data.get("language_code") or data.get("language") or "en"
                    print(f"[STT] STT complete for thread {thread_id} ({len(text)} chars). detected_language={lang}")
                    return text, lang
                if status == "error":
                    print(f"❌ AssemblyAI transcription error for thread {thread_id}: {data.get('error')}")
                    return None, None

                elapsed = time.time() - start
                if elapsed > _ASSEMBLYAI_POLL_TIMEOUT:
                    print(f"❌ AssemblyAI transcription timed out for thread {thread_id}")
                    return None, None

                await asyncio.sleep(interval)
                # gentle backoff up to ~3s
                interval = min(interval * 1.3, 3.0)

        except Exception as e:
            import traceback
            print(f"❌ STT error for thread {thread_id}: {e}")
            print(f"[STT] Error traceback for thread {thread_id}:")
            traceback.print_exc()
            return None, None

    # ---- sync wrapper for backward compatibility ----
    def speech_to_text_direct_sync(self, audio_url: str, thread_id: str = "unknown") -> Tuple[Optional[str], Optional[str]]:
        """
        Sync wrapper for speech-to-text conversion
        
        Args:
            audio_url: URL to the audio file to transcribe
            thread_id: Thread identifier for logging purposes
            
        Returns:
            Tuple of (transcribed text, detected language) or (None, None) on error
        """
        try:
            # Check if there's already a running event loop
            loop = asyncio.get_running_loop()
            # If we're in a running loop, schedule and wait for the result
            return loop.run_until_complete(self.speech_to_text_direct(audio_url, thread_id))
        except RuntimeError:
            # No running event loop, safe to use asyncio.run()
            return asyncio.run(self.speech_to_text_direct(audio_url, thread_id))

    # ---- TTS pipeline (async) ----
    async def text_to_speech_async(self, text: str, detected_language: str = "en", thread_id: str = "unknown") -> Optional[str]:
        if not self.speechgen_client:
            print(f"❌ SpeechGen client not configured for thread {thread_id}")
            return None
        try:
            tts_text = text
            tts_language = detected_language

            # Punjabi special case: translation service likely sync; run in thread
            if detected_language in ("pa", "pa_in", "pa_pk"):
                try:
                    from app.services.translation_service import TranslationService
                    temp_translation_service = TranslationService()
                    translated_text = await temp_translation_service.translate_en_to_shahmukhi(text)
                    if translated_text:
                        tts_text = translated_text
                        tts_language = "ur"
                        print(f"[TTS] Punjabi detected for thread {thread_id} — using Shahmukhi text with Urdu voice")
                    else:
                        print(f"[TTS] Punjabi translation failed for thread {thread_id} — using English text with Urdu voice")
                        tts_language = "ur"
                except Exception as e:
                    print(f"[TTS] Punjabi translation exception for thread {thread_id}: {e}")
                    tts_language = "ur"
             # Select appropriate voice for the TTS language
            voice = await self._get_voice_for_language_async(tts_language)
             # Create temporary file for the audio
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            tmp.close()
            output_path = tmp.name

            # Generate via SpeechGen (async)
            print(f"[TTS] Starting SpeechGen TTS for thread {thread_id} with voice {voice}")
            result_path = await self.speechgen_client.tts_quick(voice, tts_text, output_path)
            print(f"[TTS] SpeechGen TTS success for thread {thread_id} (voice={voice}) -> {result_path}")
            return result_path

        except Exception as e:
            import traceback
            print(f"❌ SpeechGen TTS error for thread {thread_id}: {e}")
            print(f"[TTS] Error traceback for thread {thread_id}:")
            traceback.print_exc()
            return None

    # ---- sync wrapper for compatibility ----
    def text_to_speech(self, text: str, detected_language: str = "en") -> Optional[str]:
        try:
            # Check if there's already a running event loop
            loop = asyncio.get_running_loop()
            # If we're in a running loop, schedule and wait for the result
            return loop.run_until_complete(self.text_to_speech_async(text, detected_language))
        except RuntimeError:
            # No running event loop, safe to use asyncio.run()
            return asyncio.run(self.text_to_speech_async(text, detected_language))

    def is_configured(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))


# Helper to run a coroutine inside a new event loop on a background thread (used by sync wrappers)
def _run_coro_in_thread(coro):
    result_container = {"result": None, "exc": None}

    def _target():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result_container["result"] = loop.run_until_complete(coro)
        except Exception as e:
            result_container["exc"] = e
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    t = threading.Thread(target=_target)
    t.start()
    t.join()
    if result_container["exc"]:
        raise result_container["exc"]
    return result_container["result"]


# ---------- Twilio messaging via async httpx (no sync Twilio client used) ----------
async def send_twilio_message(to_number: str, message: str, thread_id: str = "unknown"):
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
        if not all([account_sid, auth_token]):
            print(f"❌ Twilio credentials missing for message sending (thread: {thread_id})")
            return

        client = get_http_client()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        data = {"Body": message, "From": from_number, "To": to_number}
        resp = await client.post(url, data=data, auth=(account_sid, auth_token))
        resp.raise_for_status()
        j = resp.json()
        print(f"[Twilio] Sent text message for thread {thread_id}: {j.get('sid')}")
    except Exception as e:
        import traceback
        print(f"❌ Error sending Twilio message for thread {thread_id}: {e}")
        print(f"[Twilio] Error traceback for thread {thread_id}:")
        traceback.print_exc()


async def send_twilio_voice_message(to_number: str, media_url: str, thread_id: str = "unknown"):
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
        if not all([account_sid, auth_token]):
            print(f"❌ Twilio credentials missing for voice message sending (thread: {thread_id})")
            return

        client = get_http_client()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        # Twilio accepts MediaUrl for media messages; docs: send media with WhatsApp via Twilio Messages API.
        data = {"MediaUrl": media_url, "From": from_number, "To": to_number}
        resp = await client.post(url, data=data, auth=(account_sid, auth_token))
        resp.raise_for_status()
        j = resp.json()
        print(f"[Twilio] Sent voice/media message for thread {thread_id}: {j.get('sid')}")
    except Exception as e:
        import traceback
        print(f"❌ Error sending Twilio voice message for thread {thread_id}: {e}")
        print(f"[Twilio] Error traceback for thread {thread_id}:")
        traceback.print_exc()


# ---------- Background voice worker — runs an asyncio loop in a dedicated thread ----------
_voice_loop: Optional[asyncio.AbstractEventLoop] = None
_voice_loop_thread: Optional[threading.Thread] = None
_voice_async_queue: Optional[asyncio.Queue] = None
_voice_worker_running = False


async def _voice_worker_loop():
    """Coroutine that consumes tasks placed into _voice_async_queue."""
    global _voice_worker_running
    _voice_worker_running = True
    print("[VoiceProcessor] async worker loop started")
    q = _voice_async_queue
    while _voice_worker_running:
        try:
            print("[VoiceProcessor] Worker waiting for next task...")
            task_func, args, kwargs = await q.get()
            task_name = getattr(task_func, '__name__', str(task_func))
            print(f"[VoiceProcessor] Worker received task: {task_name}, args: {args[:2]}...")  # Only show first 2 args to avoid sensitive info
            try:
                if inspect.iscoroutinefunction(task_func):
                    print(f"[VoiceProcessor] Executing async task: {task_name}")
                    await task_func(*args, **kwargs)
                    print(f"[VoiceProcessor] Completed async task: {task_name}")
                else:
                    # run sync function in threadpool
                    print(f"[VoiceProcessor] Executing sync task: {task_name}")
                    await asyncio.to_thread(task_func, *args, **kwargs)
                    print(f"[VoiceProcessor] Completed sync task: {task_name}")
            except Exception as e:
                import traceback
                print(f"[VoiceProcessor] Error while executing task {task_name}: {e}")
                print(f"[VoiceProcessor] Error traceback for task {task_name}:")
                traceback.print_exc()
            finally:
                q.task_done()
                print(f"[VoiceProcessor] Task {task_name} marked as done")
        except asyncio.CancelledError:
            print("[VoiceProcessor] Worker loop received cancellation")
            break
        except Exception as e:
            import traceback
            print(f"[VoiceProcessor] Worker loop exception: {e}")
            print("[VoiceProcessor] Worker loop traceback:")
            traceback.print_exc()
            await asyncio.sleep(0.5)

    _voice_worker_running = False
    print("[VoiceProcessor] async worker loop stopped")


def _start_voice_loop_in_thread():
    global _voice_loop, _voice_loop_thread, _voice_async_queue, _voice_worker_running
    if _voice_loop_thread and _voice_loop_thread.is_alive():
        return

    def _thread_target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        global _voice_loop, _voice_async_queue
        _voice_loop = loop
        _voice_async_queue = asyncio.Queue()
        loop.create_task(_voice_worker_loop())
        try:
            loop.run_forever()
        finally:
            # cleanup
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            _voice_loop = None
            _voice_async_queue = None

    _voice_loop_thread = threading.Thread(target=_thread_target, daemon=True)
    _voice_loop_thread.start()
    # wait a short moment for loop to spin up
    timeout = 5.0
    start = time.time()
    while _voice_loop is None and time.time() - start < timeout:
        time.sleep(0.01)


def start_voice_worker():
    """Start the background voice processing worker (async loop in a thread)."""
    global _voice_worker_running
    if _voice_worker_running and _voice_loop is not None:
        return
    _start_voice_loop_in_thread()
    # flag will be set by worker coroutine
    print("[VoiceProcessor] Background worker thread started")


def queue_voice_task(task_func: Callable, *args, **kwargs):
    """Add a voice processing task to the background queue (accepts sync or async callables)."""
    if _voice_loop is None:
        start_voice_worker()
    # schedule queue.put coroutine thread-safely
    fut = asyncio.run_coroutine_threadsafe(_voice_async_queue.put((task_func, args, kwargs)), _voice_loop)
    # optional: block until scheduled or check fut.result(timeout=...)
    return fut


# ---------- Example processing pipeline (async) ----------
async def process_voice_message_background(media_url: str, thread_id: str, from_number: str):
    """
    Async processing pipeline for a single voice message. Use queue_voice_task(process_voice_message_background, ...)
    to schedule it.
    """
    try:
        print(f"[VoiceProcessor] Starting background processing for {thread_id} from {from_number}")
        
        # 1) STT
        print(f"[VoiceProcessor] STT: Starting speech-to-text conversion for {thread_id}")
        transcribed_text, detected_language = await speech_processor.speech_to_text_direct(media_url, thread_id)
        if not transcribed_text:
            print(f"[VoiceProcessor] STT: Failed to transcribe audio for {thread_id}, sending error message")
            await send_twilio_message(from_number, "Sorry, I couldn't understand the voice message.", thread_id)
            return
        print(f"[VoiceProcessor] STT: Successfully transcribed audio for {thread_id}, detected language: {detected_language}")

        # 2) Translate to English if needed (sync translation helper run in thread)
        print(f"[VoiceProcessor] Translation: Starting translation to English if needed for {thread_id}")
        english_text = transcribed_text
        if detected_language != "en":
            try:
                from app.services.translation_service import TranslationService
                temp_translation_service = TranslationService()
                _, translated_text = await temp_translation_service.detect_and_translate_to_english(transcribed_text)
                if translated_text:
                    english_text = translated_text
                    print(f"[VoiceProcessor] Translation: Successfully translated to English for {thread_id}")
                else:
                    english_text = transcribed_text
                    print(f"[VoiceProcessor] Translation: Translation returned empty for {thread_id} — using original text")
            except Exception as e:
                print(f"[VoiceProcessor] Translation: Exception occurred while translating for {thread_id}: {e}")
                english_text = transcribed_text
        else:
            print(f"[VoiceProcessor] Translation: No translation needed, already in English for {thread_id}")

        # 3) Run LangGraph (sync functions run in thread)
        print(f"[VoiceProcessor] LangGraph: Starting invocation for {thread_id}")
        from app.langgraph import create_graph, invoke_graph, extract_last_ai_text
        graph = await asyncio.to_thread(create_graph)
        print(f"[VoiceProcessor] LangGraph: Graph created successfully for {thread_id}")
        state = await asyncio.to_thread(invoke_graph, graph, english_text, thread_id, True, detected_language)
        print(f"[VoiceProcessor] LangGraph: Graph invocation completed for {thread_id}")
        reply_text = await asyncio.to_thread(extract_last_ai_text, state) or "Got it."
        print(f"[VoiceProcessor] LangGraph: Extracted AI response for {thread_id}: '{reply_text[:50]}...'")

        # 4) Translate back if needed (except Punjabi — handled in TTS pipeline)
        print(f"[VoiceProcessor] Reverse Translation: Starting if needed for {thread_id}")
        if detected_language != "en" and detected_language not in ("pa", "pa_in", "pa_pk"):
            try:
                from app.services.translation_service import TranslationService
                temp_translation_service = TranslationService()
                translated_reply = await temp_translation_service.translate_from_english(reply_text, detected_language)
                if translated_reply:
                    reply_text = translated_reply
                    print(f"[VoiceProcessor] Reverse Translation: Successfully translated back to {detected_language} for {thread_id}")
                else:
                    print(f"[VoiceProcessor] Reverse Translation: No translation returned for {thread_id}, keeping English response")
            except Exception as e:
                print(f"[VoiceProcessor] Reverse Translation: Exception occurred while translating back for {thread_id}: {e}")
        else:
            print(f"[VoiceProcessor] Reverse Translation: No reverse translation needed for {thread_id} (Punjabi handled in TTS or already English)")

        # 5) TTS (async)
        print(f"[VoiceProcessor] TTS: Starting text-to-speech conversion for {thread_id}")
        audio_file_path = await speech_processor.text_to_speech_async(reply_text, detected_language, thread_id)
        if not audio_file_path:
            print(f"[VoiceProcessor] TTS: Failed to generate audio, sending text response for {thread_id}")
            await send_twilio_message(from_number, reply_text, thread_id)
            return
        print(f"[VoiceProcessor] TTS: Successfully generated audio file for {thread_id}: {audio_file_path}")

        # 6) Upload to S3 (sync helper run in thread)
        print(f"[VoiceProcessor] S3: Starting upload for {thread_id}")
        try:
            from app.services.s3_handler import secure_tazaticket_s3
            presigned_url = await asyncio.to_thread(secure_tazaticket_s3.upload_voice_file, audio_file_path, thread_id)
            if presigned_url:
                print(f"[VoiceProcessor] S3: Successfully uploaded to S3 for {thread_id}: {presigned_url[:50]}...")
            else:
                print(f"[VoiceProcessor] S3: Failed to get presigned URL for {thread_id}")
        except Exception as e:
            print(f"[VoiceProcessor] S3: Exception occurred during upload for {thread_id}: {e}")
            presigned_url = None

        # cleanup
        print(f"[VoiceProcessor] Cleanup: Removing temporary audio file for {thread_id}")
        try:
            await asyncio.to_thread(os.unlink, audio_file_path)
            print(f"[VoiceProcessor] Cleanup: Successfully removed temporary file for {thread_id}")
        except Exception as e:
            print(f"[VoiceProcessor] Cleanup: Failed to remove temporary file for {thread_id}: {e}")

        # 7) Send voice response (Twilio async HTTP)
        print(f"[VoiceProcessor] Twilio: Starting response sending for {thread_id}")
        if presigned_url:
            print(f"[VoiceProcessor] Twilio: Sending voice message to {from_number} for {thread_id}")
            await send_twilio_voice_message(from_number, presigned_url, thread_id)
        else:
            print(f"[VoiceProcessor] Twilio: Sending text message to {from_number} for {thread_id}")
            await send_twilio_message(from_number, reply_text, thread_id)
        print(f"[VoiceProcessor] Completed processing for {thread_id}")

    except Exception as e:
        import traceback
        print(f"[VoiceProcessor] Background processing error for {thread_id}: {e}")
        print(f"[VoiceProcessor] Error traceback for {thread_id}:")
        traceback.print_exc()
        await send_twilio_message(from_number, "Sorry, there was an error processing your voice message.", thread_id)


# ---------- Initialize instance & start worker ----------
speech_processor = SpeechProcessor()
start_voice_worker()
