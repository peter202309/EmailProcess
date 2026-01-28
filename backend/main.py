import os
import time
import glob
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from google import genai
import requests
from dotenv import load_dotenv
from imap_tools import MailBox, AND
from bs4 import BeautifulSoup
import re

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

def get_all_accounts():
    """Returns a list of {user, password} dicts from .env"""
    accounts = []
    # Primary: List of accounts
    multi = os.getenv("EMAIL_ACCOUNTS")
    if multi:
        for item in multi.split(","):
            if ":" in item:
                u, p = item.split(":", 1)
                accounts.append({"user": u.strip(), "pass": p.strip()})
    
    # Fallback to single account if not already in list
    if EMAIL_ACCOUNT and EMAIL_PASSWORD:
        if not any(a['user'] == EMAIL_ACCOUNT for a in accounts):
            accounts.append({"user": EMAIL_ACCOUNT, "pass": EMAIL_PASSWORD})
            
    return accounts

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
    instruction: Optional[str] = None # For manual overrides like tone or custom prompts
    attachmentPath: Optional[str] = None # If we only want to analyze a specific file




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

@app.get("/attachments/{filename}")
def get_attachment(filename: str):
    """Serve a saved attachment file."""
    # Security: Ensure filename doesn't contain path traversal
    safe_filename = os.path.basename(filename)
    file_path = os.path.join("attachments", safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(file_path)

def clean_html(html_content):
    """Converts HTML to clean text, removing scripts and styles."""
    if not html_content:
        return ""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        # Remove script and style elements
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
        # Get text
        text = soup.get_text(separator=' ')
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text
    except Exception:
        # Fallback to simple regex if BS4 fails
        clean = re.compile('<.*?>')
        return re.sub(clean, '', html_content)

@app.get("/poll-emails")
def poll_emails(fetch_mode: str = "all"):
    """
    Connects to IMAP for all configured accounts, fetches emails, and adds them to the SQLite DB.
    """
    accounts = get_all_accounts()
    if not accounts:
        return {"error": "No email accounts configured in .env (set EMAIL_ACCOUNTS or EMAIL_ACCOUNT/PASSWORD)"}

    new_total = 0
    errors = []
    
    from datetime import date, timedelta
    since_date = date.today() - timedelta(days=1)
    
    for acc in accounts:
        user = acc['user']
        pwd = acc['pass']
        try:
            with MailBox(IMAP_SERVER).login(user, pwd) as mailbox:
                # Build search criteria based on fetch_mode
                if fetch_mode == "unread":
                    search_criteria = AND(date_gte=since_date, seen=False)
                else:
                    search_criteria = AND(date_gte=since_date)
                
                for msg in mailbox.fetch(search_criteria, reverse=True):
                    message_id = msg.headers.get('message-id', [None])[0]
                    references = msg.headers.get('references', [None])[0]
                    in_reply_to = msg.headers.get('in-reply-to', [None])[0]
                    
                    thread_id = references.split()[0] if references else (in_reply_to or message_id)
                    is_read = '\\Seen' in msg.flags

                    raw_body = msg.text or msg.html
                    # If it's HTML only, clean it
                    if not msg.text and msg.html:
                        body_text = clean_html(msg.html)
                    else:
                        body_text = msg.text or ""

                    # Capture Attachments
                    msg_attachments = []
                    for att in msg.attachments:
                        # Create a unique filename to avoid collisions
                        # Format: uid_account_filename
                        safe_acc = user.split('@')[0]
                        unique_filename = f"{msg.uid}_{safe_acc}_{att.filename}"
                        file_save_path = os.path.join("attachments", unique_filename)
                        
                        # Save the file content
                        with open(file_save_path, "wb") as f:
                            f.write(att.payload)
                        
                        msg_attachments.append({
                            "filename": att.filename,
                            "storedName": unique_filename,
                            "contentType": att.content_type,
                            "size": att.size
                        })

                    email_obj = {
                        "id": str(msg.uid),
                        "from": msg.from_,
                        "subject": msg.subject,
                        "body": body_text,
                        "receivedAt": msg.date.strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "unread",
                        "aiAnalysis": None,
                        "message_id": message_id,
                        "thread_id": thread_id,
                        "is_read": 1 if is_read else 0,
                        "account_owner": user,
                        "attachments": msg_attachments
                    }
                    if database.save_email(email_obj):
                        new_total += 1
        except Exception as e:
            err_msg = f"IMAP Error for {user}: {e}"
            print(err_msg)
            errors.append(err_msg)
                
    all_emails = database.get_all_emails()
    return {
        "status": "success" if not errors else "partial_success", 
        "new_emails_count": new_total, 
        "total_emails": len(all_emails), 
        "errors": errors if errors else None
    }

@app.get("/emails")
def get_emails():
    return database.get_all_emails()

@app.post("/reset-emails")
def reset_emails():
    """Wipe all emails, logs, and tasks."""
    database.clear_all_emails()
    return {"status": "success", "message": "Database cleared"}

@app.post("/emails/{email_id}/mark-read")
def mark_email_as_read(email_id: str):
    """Mark an email as read in the database."""
    try:
        database.mark_as_read(email_id)
        return {"status": "success", "message": f"Email {email_id} marked as read"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.post("/emails/{email_id}/resolve")
def resolve_email(email_id: str):
    """Mark an email as processed (resolved) without sending a reply."""
    try:
        database.update_email_status(email_id, "processed")
        database.log_event("RESOLVED_NO_REPLY", email_id, "Marked as resolved without reply")
        return {"status": "success", "message": f"Email {email_id} marked as resolved"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

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
    # 1. RAG Search
    rag_results = rag_service.search(f"{request.emailSubject}\n{request.emailBody}")
    
    # Format context for AI with clear source attribution
    context_str = ""
    if rag_results:
        context_str = "\n\n".join([f"[Source: {r['source']}]\n{r['content']}" for r in rag_results])
    
    prompt = f"""
    You are a professional customer service assistant. Analyze this email using the provided knowledge base context if relevant.
    
    [Knowledge Base Context]:
    {context_str if context_str else "No relevant context found in Knowledge Base."}
    
    [Email]:
    Subject: {request.emailSubject}
    Body: {request.emailBody}
    
    [Special Instructions]:
    {request.instruction if request.instruction else "Generate a professional analysis and draft reply."}
    
    Requirements:
    1. **MANDATORY Language Matching**: Detect the language of the original email. You MUST generate the 'draftReply' in the EXACT SAME language.
    2. **Confidence Score**: Assign a 'confidence' score between 0.0 and 1.0 based on how well the context matches the query.
    3. **Sources**: If you use information from the Knowledge Base Context, list the source filenames (e.g., 'policy.pdf') in 'sourcesUsed'.
    4. **Reply Detection**: Determine if this email requires a reply. Newsletters, notifications, automated messages, and informational emails do NOT require replies.
    
    Return EXACTLY a JSON object with:
    - category: (One of: Urgent, Billing, Technical, Sales, Support, Information, Spam, Newsletter)
    - confidence: (float, 0.0 to 1.0)
    - intent: (short string describing why you chose this category)
    - isUrgent: (boolean, TRUE if the email requires immediate attention)
    - requiresReply: (boolean, TRUE if this email needs a response, FALSE for newsletters/notifications/automated messages)
    - suggestedAction: (auto_reply, manual_review, ignore)
    - draftReply: (professional response in the detected language, ONLY if requiresReply is TRUE, otherwise empty string)
    - sourcesUsed: (list of strings, filenames used from context)
    """

    analysis_payload = await call_ai_with_fallback(prompt, request.provider)
    
    # Enrich the payload with RAG sources before saving
    analysis_payload["ragSources"] = list(set([r['source'] for r in rag_results])) if rag_results else []
    # Ensure sourcesUsed is a list
    if "sourcesUsed" not in analysis_payload:
        analysis_payload["sourcesUsed"] = []
    
    # PERSIST: Save analysis to DB
    database.update_email_status(request.emailId, "pending_review", analysis=analysis_payload)

    return {
        "analysis": analysis_payload.get("draftReply", ""),
        "confidence": analysis_payload.get("confidence", 0.0),
        "isUrgent": analysis_payload.get("isUrgent", False),
        "category": analysis_payload.get("category", "Information"),
        "intent": analysis_payload.get("intent", ""),
        "sourcesUsed": analysis_payload.get("sourcesUsed", []),
        "ragSources": analysis_payload["ragSources"],
        "matchedTemplate": matched_template
    }

@app.post("/analyze-attachment")
async def analyze_attachment(emailId: str, storedName: str):
    """
    Specifically analyzes an attachment using Vision capabilities.
    """
    file_path = os.path.join("attachments", storedName)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Attachment file not found")
        
    # Detect file type
    is_image = storedName.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
    is_pdf = storedName.lower().endswith('.pdf')
    
    if not (is_image or is_pdf):
        return {"status": "error", "message": "Only images and PDFs are supported for deep analysis"}

    # Use Gemini's vision capability
    if not client:
        return {"status": "error", "message": "Gemini API client not initialized"}

    try:
        mime_type = "application/pdf" if is_pdf else "image/jpeg"
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        prompt = """
        You are a document analysis assistant. Analyze this attachment and extract key information.
        If it is a receipt/invoice: Extract amounts, dates, and vendor.
        If it is a medical document/certificate: Summarize the diagnosis and duration if applicable.
        If it is an ID: Verify names and validity.
        
        Return a clear, bulleted summary in the same language as the document.
        """
        
        # Prepare parts for Gemini 2.0
        from google.genai.types import Part
        parts = [
            Part.from_bytes(data=file_bytes, mime_type=mime_type),
            Part.from_text(text=prompt)
        ]
        
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=parts
        )
        
        analysis_text = response.text
        
        # Log the event
        database.log_event("ATTACHMENT_ANALYSIS", emailId, f"Analyzed {storedName}: {analysis_text[:100]}...")
        
        return {"status": "success", "analysis": analysis_text}
    except Exception as e:
        error_msg = str(e)
        print(f"Attachment analysis error: {error_msg}")
        
        # Check for quota/rate limit errors
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
            user_message = """⚠️ **Gemini API 配额已用尽**

您的 Gemini API 免费配额已达到限制。请选择以下解决方案：

1. **等待重置** - 免费配额每天重置，请稍后再试
2. **升级到付费计划** - 访问 https://ai.google.dev/pricing 了解详情
3. **使用其他 API Key** - 在 .env 文件中更换 VITE_GEMINI_API_KEY

**当前限制：**
- 免费版：15 RPM (每分钟请求数)
- 免费版：1,500 RPD (每天请求数)

💡 提示：附件分析功能暂时不可用，但邮件分析和回复功能仍可正常使用（使用 OpenAI）。"""
            
            database.log_event("ATTACHMENT_ANALYSIS_ERROR", emailId, f"Quota exceeded for {storedName}")
            return {"status": "error", "message": user_message}
        
        # Generic error
        return {"status": "error", "message": f"分析失败: {error_msg}"}

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
    Automatically uses the SMTP credentials of the account that received the email.
    """
    try:
        # 1. Find the email and its owner
        all_emails = database.get_all_emails()
        original = next((e for e in all_emails if e['id'] == request.emailId), None)
        
        if not original:
            raise HTTPException(status_code=404, detail="Original email not found in database.")
            
        owner = original.get('accountOwner')
        accounts = get_all_accounts()
        target_acc = next((a for a in accounts if a['user'] == owner), None)
        
        # Fallback to current default if owner not found in accounts list (e.g. env changed)
        if not target_acc and accounts:
            target_acc = accounts[0]
            
        if not target_acc:
             raise HTTPException(status_code=500, detail="No valid email account found for sending.")

        # 2. Create Message
        msg = MIMEMultipart()
        msg['From'] = target_acc['user']
        msg['To'] = request.recipient
        msg['Subject'] = f"Re: {request.subject}" if not request.subject.startswith("Re:") else request.subject
        
        # Threading Headers
        if original.get('message_id'):
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

        # 3. Connect to SMTP (SSL)
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(target_acc['user'], target_acc['pass'])
            server.send_message(msg)
            
        # 4. Update DB
        database.update_email_status(request.emailId, "processed", sent_reply=request.replyBody)
        database.log_event("REPLY_SENT", request.emailId, f"Replied to {request.recipient} from {target_acc['user']}")
        
        return {"status": "success", "detail": f"Email sent successfully from {target_acc['user']}"}
        
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
    uvicorn.run(app, host="0.0.0.0", port=8010)
