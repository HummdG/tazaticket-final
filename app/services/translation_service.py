"""
Translation service using OpenAI for language detection and translation
"""
import os
from typing import Optional, Tuple
from openai import OpenAI
from google.cloud import translate_v3 as translate


class TranslationService:
    """Handles language detection and translation using OpenAI"""
    
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        if not os.getenv('OPENAI_API_KEY'):
            print("⚠️ Warning: OPENAI_API_KEY not found in environment variables")
    
    def detect_language(self, text: str) -> str:
        """
        Detect the language of the given text using OpenAI
        
        Args:
            text: Text to analyze for language detection
            
        Returns:
            Language code (e.g., 'en', 'ur', 'es', 'fr', etc.) or 'en' as fallback
        """
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a language detection expert. Analyze the given text and return ONLY the ISO 639-1 language code (2 letters) for the detected language. For example: 'en' for English, 'ur' for Urdu, 'es' for Spanish, 'fr' for French, etc. If you cannot detect the language, return 'en'."
                    },
                    {
                        "role": "user", 
                        "content": f"Detect the language of this text: {text}"
                    }
                ],
                temperature=0,
                max_tokens=10
            )
            
            detected_language = response.choices[0].message.content.strip().lower()
            print(f"🌐 Detected language: {detected_language} for text: '{text[:50]}...'")
            return detected_language
            
        except Exception as e:
            print(f"❌ Error detecting language: {e}")
            return "en"  # Default to English
    
    def translate_to_english(self, text: str, source_language: str) -> Optional[str]:
        """
        Translate text from source language to English
        
        Args:
            text: Text to translate
            source_language: Source language code
            
        Returns:
            Translated text in English or None if error
        """
        if source_language == "en":
            return text  # Already in English
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": f"""You are a professional translator. 
                        Translate the given text from {source_language} to English. 
                        Maintain the original meaning and context. Return ONLY the translated text without 
                        any explanations or additional commentary."""
                    },
                    {
                        "role": "user", 
                        "content": text
                    }
                ],
                temperature=0
            )
            
            translated_text = response.choices[0].message.content.strip()
            print(f"🔄 Translated to English: '{text[:30]}...' -> '{translated_text[:30]}...'")
            return translated_text
            
        except Exception as e:
            print(f"❌ Error translating to English: {e}")
            return None
    
    def translate_from_english(self, text: str, target_language: str) -> Optional[str]:
        """
        Translate text from English to target language
        
        Args:
            text: English text to translate
            target_language: Target language code
            
        Returns:
            Translated text in target language or None if error
        """
        if target_language == "en":
            return text  # Already in English
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": f"You are a professional translator. Translate the given English text to {target_language}. Maintain the original meaning and context. Return ONLY the translated text without any explanations or additional commentary."
                    },
                    {
                        "role": "user", 
                        "content": text
                    }
                ],
                temperature=0
            )
            
            translated_text = response.choices[0].message.content.strip()
            print(f"🔄 Translated to {target_language}: '{text[:30]}...' -> '{translated_text[:30]}...'")
            return translated_text
            
        except Exception as e:
            print(f"❌ Error translating to {target_language}: {e}")
            return None
    
    def detect_and_translate_to_english(self, text: str) -> Tuple[str, Optional[str]]:
        """
        Detect language and translate to English if needed
        
        Args:
            text: Text to process
            
        Returns:
            Tuple of (detected_language, translated_text_or_original)
        """
        detected_language = self.detect_language(text)
        
        if detected_language == "en":
            return detected_language, text
        
        translated_text = self.translate_to_english(text, detected_language)
        return detected_language, translated_text
    
    def translate_en_to_shahmukhi(self, text: str) -> Optional[str]:
        """
        Translate English text to Punjabi (Shahmukhi / Arabic script) using Google Cloud Translation v3.
        
        Args:
            text: English text to translate
            
        Returns:
            Translated text in Punjabi (Shahmukhi) or None if error
        """
        try:
            # Get project ID from environment variable
            project_id = os.getenv('GOOGLE_CLOUD_PROJECT_ID')
            if not project_id:
                print("⚠️ Warning: GOOGLE_CLOUD_PROJECT_ID not found in environment variables")
                return None
            
            client = translate.TranslationServiceClient()
            parent = f"projects/{project_id}/locations/global"

            response = client.translate_text(
                request={
                    "parent": parent,
                    "contents": [text],
                    "mime_type": "text/plain",
                    "source_language_code": "en",
                    "target_language_code": "pa-Arab",
                }
            )

            # API returns a list; we asked for one string, so take the first.
            translated_text = response.translations[0].translated_text
            print(f"🔄 Translated to Punjabi (Shahmukhi): '{text[:30]}...' -> '{translated_text[:30]}...'")
            return translated_text
            
        except Exception as e:
            print(f"❌ Error translating to Punjabi (Shahmukhi): {e}")
            return None
    
    def is_configured(self) -> bool:
        """Check if OpenAI API key is configured"""
        return bool(os.getenv('OPENAI_API_KEY'))


# Global translation service instance
translation_service = TranslationService() 