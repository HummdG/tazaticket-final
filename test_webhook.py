import subprocess
import time
import threading
import sys
from client import WebhookClient

def run_server():
    """Run the FastAPI server in a separate thread"""
    subprocess.run([sys.executable, "main.py"])

def main():
    print("Starting Tazaticket webhook tests...")
    print("=====================================")
    
    # Start the server in a separate thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Give the server some time to start up
    time.sleep(3)
    
    # Initialize the client
    client = WebhookClient("http://localhost:8000")
    
    # Test 1: Check if server is running
    print("Test 1: Checking if server is running...")
    try:
        import requests
        health_response = requests.get("http://localhost:8000/")
        if health_response.status_code == 200:
            print("✓ Server is running")
        else:
            print(f"✗ Server issue: {health_response.status_code}")
            return
    except Exception as e:
        print(f"✗ Server not accessible: {e}")
        return
    print()
    
    # Test 2: Send a simple text message
    print("Test 2: Sending text message...")
    try:
        response = client.send_text_message("Hello, this is a test message!")
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text}")
    except Exception as e:
        print(f"✗ Error sending message: {e}")
    print()
    
    # Test 3: Send a message in Spanish to test translation
    print("Test 3: Sending Spanish message to test translation...")
    try:
        response = client.send_text_message("Hola, ¿cómo estás?", from_number="whatsapp:+34678901234", wa_id="whatsapp+34678901234")
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text}")
    except Exception as e:
        print(f"✗ Error sending Spanish message: {e}")
    print()
    
    print("Tests completed. The server is still running in the background.")
    print("Press Ctrl+C to stop.")


if __name__ == "__main__":
    main()