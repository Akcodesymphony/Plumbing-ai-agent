
# plumbing_ai_agent_optimized.py (Google Gemini 1.5 version)

from typing import TypedDict, Optional
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
import uuid, json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai

genai.configure(api_key="YOUR_GEMINI_API_KEY")
model = genai.GenerativeModel("gemini-1.5-flash")

def get_gemini_response(prompt: str) -> str:
    response = model.generate_content(prompt)
    return response.text.strip()

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", SCOPE)
client = gspread.authorize(creds)
SHEET_NAME = "PlumbingJobs"
sheet = client.open(SHEET_NAME).sheet1

usage_stats = {"token_count": 0, "job_count": 0}

def track_usage(tokens=0, job=False):
    usage_stats["token_count"] += tokens
    if job:
        usage_stats["job_count"] += 1
    with open("usage.json", "w") as f:
        json.dump(usage_stats, f)

class PlumbingState(TypedDict):
    user_message: str
    intent: Optional[str]
    response: Optional[str]
    job_type: Optional[str]
    user_location: Optional[str]
    customer_name: Optional[str]
    email: Optional[str]
    date_requested: Optional[str]
    job_id: Optional[str]

def classify_intent(state: PlumbingState) -> PlumbingState:
    prompt = f"What is the intent of this message? '{state['user_message']}'? Choose one: [book_appointment, get_quote, job_status, generate_invoice, unknown]"
    intent = get_gemini_response(prompt).lower().strip()
    state["intent"] = intent
    return state

def book_appointment(state: PlumbingState) -> PlumbingState:
    job_id = str(uuid.uuid4())
    date = (datetime.utcnow() + timedelta(days=1)).isoformat()
    state.update({
        "job_id": job_id,
        "date_requested": date,
        "response": f"Your plumbing job has been scheduled for {date}. Job ID: {job_id}"
    })
    sheet.append_row([
        job_id,
        state.get("customer_name", "Client"),
        state.get("job_type", "Unspecified"),
        date,
        state.get("email", "not_provided@example.com")
    ])
    track_usage(job=True)
    return state

def get_quote(state: PlumbingState) -> PlumbingState:
    state["response"] = "Please describe the plumbing issue you need a quote for."
    return state

def check_status(state: PlumbingState) -> PlumbingState:
    state["response"] = "Please provide your job ID or email to check status."
    return state

def generate_invoice(state: PlumbingState) -> PlumbingState:
    state["response"] = "To generate an invoice, please share the job ID."
    return state

def fallback_node(state: PlumbingState) -> PlumbingState:
    state["response"] = "I'm not sure what you mean. Do you want to book, get a quote, or check job status?"
    return state

def router(state: PlumbingState):
    intent = state.get("intent", "unknown")
    return {
        "book_appointment": "book",
        "get_quote": "quote",
        "job_status": "status",
        "generate_invoice": "invoice"
    }.get(intent, "fallback")

from langgraph.graph import StateGraph

builder = StateGraph(PlumbingState)
builder.add_node("classify", classify_intent)
builder.add_node("book", book_appointment)
builder.add_node("quote", get_quote)
builder.add_node("status", check_status)
builder.add_node("invoice", generate_invoice)
builder.add_node("fallback", fallback_node)

builder.set_entry_point("classify")
builder.add_conditional_edges("classify", router)

for node in ["book", "quote", "status", "invoice", "fallback"]:
    builder.set_finish_point(node)

graph = builder.compile()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserInput(BaseModel):
    message: str

@app.post("/chat")
def chat(input: UserInput):
    result = graph.invoke({"user_message": input.message})
    return {"response": result["response"]}

@app.get("/usage")
def get_usage():
    return usage_stats

