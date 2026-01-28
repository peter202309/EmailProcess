import os
import time
import glob
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from google import genai
import requests
from dotenv import load_dotenv
from imap_tools import MailBox, AND

from rag import RAGService
import database

# Load environment variables
load_dotenv(dotenv_path="../.env")

# Initialize DB
database.init_db()

app = FastAPI()
# Initialize RAG
rag_service = RAGService()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gemini Config
GEMINI_API_KEY = os.getenv("VITE_GEMINI_API_KEY")
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

import smtplib
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# ... previous imports ...

# IMAP & SMTP Config
IMAP_SERVER = os.getenv("IMAP_SERVER")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Models
class SendReplyRequest(BaseModel):
    emailId: str
    recipient: str
    subject: str
    replyBody: str
    originalStatus: Optional[str] = None
    attachments: Optional[List[dict]] = None # List of {filename: str, content: base64_str}
class EmailSchema(BaseModel):
    id: str
    from_addr: str
    subject: str
    body: str
    receivedAt: str
    status: str
    aiAnalysis: Optional[dict] = None

class ProcessingRequest(BaseModel):
    emailId: str
    emailBody: Optional[str] = ""
    emailSubject: Optional[str] = ""
    provider: Optional[str] = 'gemini'
    category: Optional[str] = None
    isUrgent: Optional[bool] = None
    intent: Optional[str] = None
    draftReply: Optional[str] = None
    updateOnly: Optional[bool] = False




class TemplateSchema(BaseModel):
    id: str
    name: str
    content: str
    keywords: Optional[str] = ""

class SettingSchema(BaseModel):
    key: str
    value: str

class DebugLogRequest(BaseModel):
    level: str  # INFO, ERROR, DEBUG
    component: str
    event: str
    data: Optional[dict] = None

class TaskSchema(BaseModel):
    title: str
    description: Optional[str] = ""
    priority: Optional[str] = "Normal"
    status: Optional[str] = "pending"
    due_date: Optional[str] = None
    email_id: Optional[str] = None

class TaskStatusUpdate(BaseModel):
    status: str

# --- Templates Routes ---
@app.get("/templates")
def get_templates():
    return database.get_templates()

@app.post("/templates")
def save_template(template: TemplateSchema):
    database.save_template(template.id, template.name, template.content, template.keywords or "")
    return {"status": "success"}

@app.delete("/templates/{id}")
def delete_template(id: str):
    database.delete_template(id)
    return {"status": "success"}

# --- Settings Routes ---
@app.get("/settings")
def get_settings():
    return database.get_settings()

@app.post("/settings")
def save_setting(setting: SettingSchema):
    database.save_setting(setting.key, setting.value)
    return {"status": "success"}

# --- Logs Routes ---
@app.get("/logs")
def get_logs():
    return database.get_logs()

@app.get("/kb-status")
def get_kb_status():
    """
    Checks if the knowledge base index exists and returns statistics.
    """
    has_index = os.path.exists("faiss_index")
    kb_files = glob.glob(os.path.join("knowledge_base", "*"))
    store_type = rag_service.store_type if rag_service else "unknown"
    return {
        "active": has_index or (store_type == "openai"),
        "doc_count": len(kb_files),
        "files": [os.path.basename(f) for f in kb_files],
        "store_type": store_type
    }

@app.post("/rebuild-kb")
def rebuild_kb():
    """
    Rebuild the Knowledge Base index from documents in knowledge_base/ folder.
    """
    try:
        from build_kb import build_index
        result = build_index()
        # Reload RAG service to pick up new index
        global rag_service
        rag_service = RAGService()
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/")
def read_root():
    return {"status": "ok", "service": "AI Mailguard Backend", "imap_user": EMAIL_ACCOUNT, "gemini_sdk": "v2.0"}

@app.get("/poll-emails")
def poll_emails():
    """
    Connects to IMAP, fetches unseen emails, and adds them to the SQLite DB.
    """
    if not EMAIL_PASSWORD or EMAIL_PASSWORD == "your_password_here":
        return {"error": "Email password not configured in .env"}

    new_count = 0
    try:
        from datetime import date, timedelta
        since_date = date.today() - timedelta(days=1)
        
        with MailBox(IMAP_SERVER).login(EMAIL_ACCOUNT, EMAIL_PASSWORD) as mailbox:
            # Fetch ALL messages from the last 24 hours (using date_gte for IMAP)
            for msg in mailbox.fetch(AND(date_gte=since_date), reverse=True):
                # Extract Threading Info
                message_id = msg.headers.get('message-id', [None])[0]
                references = msg.headers.get('references', [None])[0]
                in_reply_to = msg.headers.get('in-reply-to', [None])[0]
                
                # Simple thread_id logic: use References or Message-ID
                thread_id = references.split()[0] if references else (in_reply_to or message_id)

                email_obj = {
                    "id": str(msg.uid),
                    "from": msg.from_,
                    "subject": msg.subject,
                    "body": msg.text or msg.html,
                    "receivedAt": msg.date.strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "unread",
                    "aiAnalysis": None,
                    "message_id": message_id,
                    "thread_id": thread_id
                }
                if database.save_email(email_obj):
                    new_count += 1
                
        all_emails = database.get_all_emails()
        return {"status": "success", "new_emails_count": new_count, "total_emails": len(all_emails), "emails": all_emails}
    except Exception as e:
        print(f"IMAP Error: {e}")
        return {"status": "error", "detail": str(e)}

@app.get("/emails")
def get_emails():
    return database.get_all_emails()

@app.post("/analyze-email")
async def analyze_email(request: ProcessingRequest):
    """
    Manually trigger AI analysis for an email using either Gemini or Groq.
    Also checks for traditional keyword-based template matches.
    If 'updateOnly' is True, it simply persists the provided metadata and skips AI.
    """
    if request.updateOnly:
        analysis_payload = {
            "draftReply": request.draftReply,
            "confidence": 1.0,
            "isUrgent": request.isUrgent,
            "category": request.category,
            "intent": request.intent
        }
        database.update_email_status(request.emailId, "pending_review", analysis=analysis_payload)
        return {"status": "updated", "category": request.category}

    # 1. Traditional Keyword Matching
    templates = database.get_templates()
    matched_template = None
    email_text = f"{request.emailSubject} {request.emailBody}".lower()
    
    for t in templates:
        keywords_str = t.get('keywords', '')
        if keywords_str:
            keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]
            if any(kw in email_text for kw in keywords if kw):
                matched_template = t
                break

    # 2. Retrieve RAG Context
    rag_context = rag_service.search(f"{request.emailSubject}\n{request.emailBody}")
    
    prompt = f"""
    You are a professional customer service assistant. Analyze this email using the provided knowledge base context if relevant.
    
    [Knowledge Base Context]:
    {rag_context}
    
    [Email]:
    Subject: {request.emailSubject}
    Body: {request.emailBody}
    
    Requirements:
    1. **MANDATORY Language Matching**: Detect the language of the original email. You MUST generate the 'draftReply' in the EXACT SAME language.
    2. **Confidence Score**: Assign a 'confidence' score between 0.0 and 1.0 based on how well the context matches the query.
    3. **Reply Detection**: Determine if this email requires a reply. Newsletters, notifications, automated messages, and informational emails do NOT require replies.
    
    Return EXACTLY a JSON object with:
    - category: (One of: Urgent, Billing, Technical, Sales, Support, Information, Spam, Newsletter)
    - confidence: (float, 0.0 to 1.0)
    - intent: (short string describing why you chose this category)
    - isUrgent: (boolean, TRUE if the email requires immediate attention)
    - requiresReply: (boolean, TRUE if this email needs a response, FALSE for newsletters/notifications/automated messages)
    - suggestedAction: (auto_reply, manual_review, ignore)
    - draftReply: (professional response in the detected language, ONLY if requiresReply is TRUE, otherwise empty string)
    """

    analysis_payload = await call_ai_with_fallback(prompt, request.provider)
    
    # PERSIST: Save analysis to DB
    database.update_email_status(request.emailId, "pending_review", analysis=analysis_payload)

    return {
        "analysis": analysis_payload["draftReply"],
        "confidence": analysis_payload["confidence"],
        "isUrgent": analysis_payload["isUrgent"],
        "category": analysis_payload["category"],
        "intent": analysis_payload["intent"],
        "matchedTemplate": matched_template
    }

async def call_ai_with_fallback(prompt: str, primary_provider: str):
    """
    Attempts to call the primary provider. If it hits a quota/rate limit, 
    automatically falls back to the other provider if available.
    """
    # Define priority chain. Primary comes first.
    all_providers = ['gemini', 'deepseek', 'openai', 'groq']
    
    # Reorder to put primary first
    providers = [primary_provider] + [p for p in all_providers if p != primary_provider]
    
    last_error = None
    for provider in providers:
        try:
            if provider == 'groq':
                return _call_groq_sync(prompt)
            elif provider == 'openai':
                return _call_openai_compatible(prompt, "https://api.openai.com/v1", os.getenv("OPENAI_API_KEY"), "gpt-4o")
            elif provider == 'deepseek':
                return _call_openai_compatible(prompt, "https://api.deepseek.com/v1", os.getenv("DEEPSEEK_API_KEY"), "deepseek-chat")
            else:
                return _call_gemini_sync(prompt)
        except Exception as e:
            last_error = e
            # Log the fallback attempt
            error_msg = str(e).lower()
            if any(key in error_msg for key in ["quota", "exhausted", "429", "rate limit", "insufficient", "not found"]):
                print(f"Fallback Warning: {provider} unavailable or quota reached. Trying next...")
                continue # Try the next one
            else:
                print(f"Provider Error ({provider}): {e}")
                continue

    raise HTTPException(status_code=500, detail=f"All AI providers failed. Last error: {last_error}")

def _call_openai_compatible(prompt: str, base_url: str, api_key: str, model: str):
    if not api_key:
        raise Exception(f"API Key for model {model} not found")
    
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"} if "openai" in base_url or "deepseek" in base_url else None
        },
        timeout=30
    )
    response.raise_for_status()
    analysis_text = response.json()["choices"][0]["message"]["content"]
    
    import json
    try:
        start = analysis_text.find('{')
        end = analysis_text.rfind('}') + 1
        res_data = json.loads(analysis_text[start:end])
        return {
            "draftReply": res_data.get("draftReply", ""),
            "confidence": float(res_data.get("confidence", 0.0)),
            "isUrgent": bool(res_data.get("isUrgent", False)),
            "requiresReply": bool(res_data.get("requiresReply", True)),
            "category": res_data.get("category", "Information"),
            "intent": res_data.get("intent", ""),
        }
    except:
        raise Exception(f"Failed to parse JSON from {model}")

def _call_groq_sync(prompt: str):
    groq_key = os.getenv("VITE_GROQ_API_KEY")
    if not groq_key:
        raise Exception("Groq API Key not found")
    
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {groq_key}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=30
    )
    response.raise_for_status()
    analysis_text = response.json()["choices"][0]["message"]["content"]
    
    import json
    start = analysis_text.find('{')
    end = analysis_text.rfind('}') + 1
    res_data = json.loads(analysis_text[start:end])
    return {
        "draftReply": res_data.get("draftReply", analysis_text),
        "confidence": float(res_data.get("confidence", 0.0)),
        "isUrgent": bool(res_data.get("isUrgent", False)),
        "requiresReply": bool(res_data.get("requiresReply", True)),
        "category": res_data.get("category", "Information"),
        "intent": res_data.get("intent", ""),
    }

def _call_gemini_sync(prompt: str):
    if not client:
        raise Exception("Gemini client not initialized")
    
    response = client.models.generate_content(
        model='gemini-2.0-flash', 
        contents=prompt,
        config={'response_mime_type': 'application/json'}
    )
    import json
    res_data = json.loads(response.text)
    return {
        "draftReply": res_data.get("draftReply", ""),
        "confidence": float(res_data.get("confidence", 0.0)),
        "isUrgent": bool(res_data.get("isUrgent", False)),
        "category": res_data.get("category", "Information"),
        "intent": res_data.get("intent", ""),
    }

# --- Tasks Routes ---
@app.get("/tasks")
def get_tasks():
    return database.get_tasks()

@app.post("/tasks")
def create_task(task: TaskSchema):
    database.save_task(task.dict())
    return {"status": "success"}

@app.patch("/tasks/{task_id}")
def update_task(task_id: int, update: TaskStatusUpdate):
    database.update_task_status(task_id, update.status)
    return {"status": "success"}

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    database.delete_task(task_id)
    return {"status": "success"}

@app.post("/send-reply")
def send_reply(request: SendReplyRequest):
    """
    Sends an email via SMTP and updates the database status.
    """
    if not EMAIL_PASSWORD or EMAIL_PASSWORD == "your_password_here":
        raise HTTPException(status_code=500, detail="Email password not configured.")

    try:
        # Get Original Email for Threading
        all_emails = database.get_all_emails()
        original = next((e for e in all_emails if e['id'] == request.emailId), None)
        
        # 1. Create Message
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ACCOUNT
        msg['To'] = request.recipient
        msg['Subject'] = f"Re: {request.subject}" if not request.subject.startswith("Re:") else request.subject
        
        # Threading Headers
        if original and original.get('message_id'):
            msg['In-Reply-To'] = original['message_id']
            msg['References'] = original['message_id']
        
        msg.attach(MIMEText(request.replyBody, 'plain'))
        
        # Attachments
        if request.attachments:
            for attach in request.attachments:
                file_name = attach.get('filename')
                content = attach.get('content') # Base64
                if file_name and content:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(base64.b64decode(content))
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{file_name}"')
                    msg.attach(part)

        # 2. Connect to SMTP (SSL)
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
            server.send_message(msg)
            
        # 3. Update DB with History
        database.update_email_status(request.emailId, "processed", sent_reply=request.replyBody)
        database.log_event("REPLY_SENT", request.emailId, f"Replied to {request.recipient}")
        
        return {"status": "success", "detail": "Email sent successfully"}
        
    except Exception as e:
        print(f"SMTP Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/debug-log")
def post_debug_log(request: DebugLogRequest):
    """
    Writes a debug log to a local file 'debug.log'
    """
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{request.level}] [{request.component}] {request.event}\n"
    if request.data:
        log_entry += f"   Data: {request.data}\n"
    
    with open("debug.log", "a", encoding="utf-8") as f:
        f.write(log_entry)
    
    # Also print to terminal
    print(log_entry.strip())
    
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
