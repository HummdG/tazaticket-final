"""
Hugging Face TTS fallback service using MohamedRashad/Multilingual-TTS
This service is used when SpeechGen.io is not working
"""
import os
import tempfile
from typing import Optional, Dict, List
from gradio_client import Client


class HuggingFaceTTS:
    """Minimal Hugging Face TTS client using MohamedRashad/Multilingual-TTS"""
    
    def __init__(self):
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the Gradio client"""
        try:
            self.client = Client("MohamedRashad/Multilingual-TTS")
            print("✅ HuggingFace TTS initialized")
        except Exception as e:
            print(f"❌ Failed to initialize HuggingFace TTS: {e}")
            self.client = None
    
    def get_speakers(self, language: str) -> Optional[List[str]]:
        """Get available speakers for a language"""
        if not self.client:
            return None
        
        try:
            result = self.client.predict(
                language=language,
                api_name="/get_speakers"
            )
            # Result is a tuple: (speakers_list, tashkeel_checkbox)
            speakers = result[0] if result and len(result) > 0 else []
            return speakers
        except Exception as e:
            print(f"❌ Error getting speakers for {language}: {e}")
            return None
    
    def text_to_speech(self, text: str, language: str, speaker: Optional[str] = None, 
                      tashkeel: bool = False) -> Optional[str]:
        """
        Convert text to speech using HuggingFace TTS
        
        Args:
            text: Text to convert to speech
            language: Language name (e.g., 'English', 'Arabic', 'Urdu')
            speaker: Speaker name (if None, will use first available speaker)
            tashkeel: Whether to use tashkeel for Arabic text
            
        Returns:
            Path to the generated audio file or None if error
        """
        if not self.client:
            print("❌ HuggingFace TTS client not initialized")
            return None
        
        try:
            # Get speakers if none provided
            if speaker is None:
                speakers = self.get_speakers(language)
                if speakers and len(speakers) > 0:
                    speaker = speakers[0]
                    print(f"🗣️ Using first available speaker: {speaker} for {language}")
                else:
                    print(f"⚠️ No speakers found for {language}")
                    return None
            
            # Generate speech
            result = self.client.predict(
                text=text,
                language_code=language,
                speaker=speaker,
                tashkeel_checkbox=tashkeel,
                api_name="/text_to_speech_edge"
            )
            
            # Result is a tuple: (output_text, audio_file_path)
            if result and len(result) > 1:
                audio_file_path = result[1]
                if audio_file_path and os.path.exists(audio_file_path):
                    print(f"🔊 HuggingFace TTS successful: {text[:50]}... (speaker: {speaker})")
                    return audio_file_path
                else:
                    print(f"❌ Audio file not generated or not found: {audio_file_path}")
                    return None
            else:
                print(f"❌ Invalid result from HuggingFace TTS: {result}")
                return None
                
        except Exception as e:
            print(f"❌ HuggingFace TTS error: {e}")
            return None
    
    def _map_language_code_to_name(self, lang_code: str) -> str:
        """Map language codes to HuggingFace language names"""
        lang_map = {
            'en': 'English',
            'es': 'Spanish', 
            'ar': 'Arabic',
            'ko': 'Korean',
            'th': 'Thai',
            'vi': 'Vietnamese',
            'ja': 'Japanese',
            'fr': 'French',
            'pt': 'Portuguese',
            'id': 'Indonesian',
            'he': 'Hebrew',
            'it': 'Italian',
            'nl': 'Dutch',
            'ms': 'Malay',
            'no': 'Norwegian',
            'sv': 'Swedish',
            'el': 'Greek',
            'de': 'German',
            'af': 'Afrikaans',
            'am': 'Amharic',
            'az': 'Azerbaijani',
            'bg': 'Bulgarian',
            'bn': 'Bengali',
            'bs': 'Bosnian',
            'ca': 'Catalan',
            'cs': 'Czech',
            'cy': 'Welsh',
            'da': 'Danish',
            'et': 'Estonian',
            'fa': 'Persian',
            'fi': 'Finnish',
            'ga': 'Irish',
            'gl': 'Galician',
            'gu': 'Gujarati',
            'hi': 'Hindi',
            'hr': 'Croatian',
            'hu': 'Hungarian',
            'is': 'Icelandic',
            'jv': 'Javanese',
            'ka': 'Georgian',
            'kk': 'Kazakh',
            'km': 'Khmer',
            'kn': 'Kannada',
            'lo': 'Lao',
            'lt': 'Lithuanian',
            'lv': 'Latvian',
            'mk': 'Macedonian',
            'ml': 'Malayalam',
            'mn': 'Mongolian',
            'mr': 'Marathi',
            'mt': 'Maltese',
            'my': 'Burmese',
            'ne': 'Nepali',
            'pl': 'Polish',
            'ps': 'Pashto',
            'ro': 'Romanian',
            'ru': 'Russian',
            'si': 'Sinhala',
            'sk': 'Slovak',
            'sl': 'Slovenian',
            'so': 'Somali',
            'sq': 'Albanian',
            'sr': 'Serbian',
            'su': 'Sundanese',
            'sw': 'Swahili',
            'ta': 'Tamil',
            'te': 'Telugu',
            'tr': 'Turkish',
            'uk': 'Ukrainian',
            'ur': 'Urdu',
            'uz': 'Uzbek',
            'zh': 'Mandarin',
            'zu': 'Zulu'
        }
        
        # Handle language variants by taking the base language
        base_lang = lang_code.split('_')[0].split('-')[0].lower()
        return lang_map.get(base_lang, 'English')
    
    def tts_with_language_code(self, text: str, detected_language: str = "en") -> Optional[str]:
        """
        Convert text to speech with automatic language mapping
        This method matches the interface used by SpeechProcessor
        
        Args:
            text: Text to convert to speech
            detected_language: Language code (e.g., 'en', 'ur', 'ar')
            
        Returns:
            Path to the generated audio file or None if error
        """
        # Map language code to HuggingFace language name
        language_name = self._map_language_code_to_name(detected_language)
        
        # Special handling for Arabic text (enable tashkeel)
        tashkeel = language_name == 'Arabic'
        
        return self.text_to_speech(text, language_name, tashkeel=tashkeel)
    
    def is_available(self) -> bool:
        """Check if the HuggingFace TTS service is available"""
        return self.client is not None


# Global HuggingFace TTS instance
huggingface_tts = HuggingFaceTTS()
