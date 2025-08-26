import os 
from dotenv import load_dotenv
import html

from fastapi import FastAPI, Form
from fastapi.responses import Response

# Import our LangGraph configuration
from app.langgraph import create_graph, invoke_graph, extract_last_ai_text

# Create the graph
graph = create_graph()

# Create FastAPI app
app = FastAPI()

@app.get("/")
async def healthcheck():
    return {"status": "ok"}

@app.post("/webhook")
async def twilio_whatsapp(Body: str = Form(...), From: str | None = Form(default=None), WaId: str | None = Form(default=None)):
    thread_id = WaId or From or "whatsapp-default"
    try:
        state = invoke_graph(graph, Body, thread_id)
        reply_text = extract_last_ai_text(state) or "Got it."
    except Exception as e:
        reply_text = f"Error: {e}"
    # Return TwiML so Twilio replies to the user
    twiml = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>{html.escape(reply_text)}</Message></Response>"
    return Response(content=twiml, media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)

