import requests
import time
import os

class WebhookClient:
    """
    A client to send messages to the Tazaticket WhatsApp webhook for testing purposes.
    """
    
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.webhook_url = f"{base_url}/webhook"
    
    def send_text_message(self, body, from_number="whatsapp:+1234567890", wa_id="whatsapp+1234567890"):
        """
        Send a text message to the webhook
        
        Args:
            body (str): The message body to send
            from_number (str): The sender's number in WhatsApp format (default: whatsapp:+1234567890)
            wa_id (str): The WhatsApp ID (default: whatsapp+1234567890)
        
        Returns:
            requests.Response: The response from the webhook
        """
        data = {
            "Body": body,
            "From": from_number,
            "WaId": wa_id
        }
        
        response = requests.post(self.webhook_url, data=data)
        return response
    
    def send_voice_message(self, media_url, from_number="whatsapp:+1234567890", wa_id="whatsapp+1234567890"):
        """
        Send a voice message to the webhook
        
        Args:
            media_url (str): URL to the audio file
            from_number (str): The sender's number in WhatsApp format
            wa_id (str): The WhatsApp ID
        
        Returns:
            requests.Response: The response from the webhook
        """
        data = {
            "Body": "",  # Empty body for voice messages
            "From": from_number,
            "WaId": wa_id,
            "MediaUrl0": media_url,
            "MediaContentType0": "audio/ogg"  # Assuming it's an audio file
        }
        
        response = requests.post(self.webhook_url, data=data)
        return response
    
    def send_unsupported_media(self, media_url, from_number="whatsapp:+1234567890", wa_id="whatsapp+1234567890"):
        """
        Send an unsupported media type to test rejection logic
        
        Args:
            media_url (str): URL to the unsupported media file
            from_number (str): The sender's number in WhatsApp format
            wa_id (str): The WhatsApp ID
        
        Returns:
            requests.Response: The response from the webhook
        """
        data = {
            "Body": "",
            "From": from_number,
            "WaId": wa_id,
            "MediaUrl0": media_url,
            "MediaContentType0": "image/jpeg"  # Unsupported media type
        }
        
        response = requests.post(self.webhook_url, data=data)
        return response


def main():
    # Initialize the client
    client = WebhookClient()
    
    print("Tazaticket WhatsApp Webhook Client")
    print("===================================")
    
    # Get the base URL from environment variable or use default
    base_url = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")
    client = WebhookClient(base_url)
    
    print(f"Using base URL: {base_url}")
    print()
    
    # Test 1: Send a simple text message
    # print("Test 1: Sending text message...")
    # response = client.send_text_message("Hello, this is a test message!")
    # print(f"Response status: {response.status_code}")
    # print(f"Response content: {response.text}")
    # print()
    
    # time.sleep(1)  # Pause between requests
    
    # # Test 2: Send a longer message
    # print("Test 2: Sending longer message...")
    # response = client.send_text_message("This is a longer test message to see how the system handles more complex inputs and processes them correctly through the LangGraph implementation.")
    # print(f"Response status: {response.status_code}")
    # print(f"Response content: {response.text}")
    # print()
    
    # time.sleep(1)  # Pause between requests
    
    # Test 3: Send a message with non-English text (to test translation)
    print("Test 3: Sending message in roman Urdu (to test translation)...")
    response = client.send_text_message("Mjhy islamabad to dxb flight, December mid mien chahiye", from_number="whatsapp:+34678901234", wa_id="whatsapp+34678901234")
    print(f"Response status: {response.status_code}")
    print(f"Response content: {response.text}")
    print()
    
    time.sleep(1)  # Pause between requests
    
    # # Test 4: Try sending a voice message (with a placeholder URL)
    # print("Test 4: Sending voice message (with placeholder URL)...")
    # # response = client.send_voice_message("https://example.com/audio.ogg")
    # print(f"Response status: {response.status_code}")
    # print(f"Response content: {response.text}")


    
    # print()
    
    # time.sleep(1)  # Pause between requests
    
    # # Test 5: Try sending unsupported media (to test rejection logic)
    # print("Test 5: Sending unsupported media (to test rejection)...")
    # response = client.send_unsupported_media("https://example.com/image.jpg")
    # print(f"Response status: {response.status_code}")
    # print(f"Response content: {response.text}")
    # print()


if __name__ == "__main__":
    main()