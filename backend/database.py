import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

DB_NAME = "mailguard.db"

@contextmanager
def get_db_connection():
    """
    Context manager for safe database connections.
    Automatically handles connection opening, committing, and closing.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        yield conn
        conn.commit()
    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

def safe_db_operation(func):
    """
    Decorator for database operations that ensures proper connection handling.
    """
    def wrapper(*args, **kwargs):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    import time
                    time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                    continue
                raise e
            except Exception as e:
                raise e
        return None
    return wrapper

def init_db():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    
    # Check if we need to migrate the emails table to composite primary key
    c.execute("PRAGMA table_info(emails)")
    e_cols = {col[1]: col for col in c.fetchall()}
    
    needs_recreate = False
    if "emails" in [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
        # If ID is primary key but not account_owner, we need to recreate
        id_col = e_cols.get("id")
        if id_col and id_col[5] == 1: # pk flag is 1
            # Check if it's a composite PK with account_owner
            # In SQLite PRAGMA table_info, pk > 0 indicates part of PK. 
            # If multiple columns have pk > 0, it's composite.
            pk_cols = [name for name, info in e_cols.items() if info[5] > 0]
            if len(pk_cols) < 2:
                needs_recreate = True

    if needs_recreate:
        print("Migrating emails table to composite primary key...")
        c.execute("ALTER TABLE emails RENAME TO emails_old")
        c.execute('''
            CREATE TABLE emails (
                id TEXT,
                from_addr TEXT,
                subject TEXT,
                body TEXT,
                received_at TEXT,
                status TEXT,
                ai_analysis TEXT,
                message_id TEXT,
                thread_id TEXT,
                sent_reply TEXT,
                sent_at TEXT,
                is_read INTEGER DEFAULT 0,
                account_owner TEXT,
                attachments_json TEXT, -- Metadata for attachments
                PRIMARY KEY (id, account_owner)
            )
        ''')
        # Copy old data - note that some older records might have NULL account_owner
        # We'll fill them with 'unknown' or the primary account if we could, 
        # but for now let's just use what's there.
        c.execute('''
            INSERT OR IGNORE INTO emails (id, from_addr, subject, body, received_at, status, ai_analysis, message_id, thread_id, sent_reply, sent_at, is_read, account_owner)
            SELECT id, from_addr, subject, body, received_at, status, ai_analysis, message_id, thread_id, sent_reply, sent_at, is_read, account_owner FROM emails_old
        ''')
        c.execute("DROP TABLE emails_old")
        print("Migration complete.")
    else:
        # Create Emails Table if not exists
        c.execute('''
            CREATE TABLE IF NOT EXISTS emails (
                id TEXT,
                from_addr TEXT,
                subject TEXT,
                body TEXT,
                received_at TEXT,
                status TEXT,
                ai_analysis TEXT,
                message_id TEXT,
                thread_id TEXT,
                sent_reply TEXT,
                sent_at TEXT,
                is_read INTEGER DEFAULT 0,
                account_owner TEXT,
                PRIMARY KEY (id, account_owner)
            )
        ''')
    
    # Re-check columns for other tables
    c.execute("PRAGMA table_info(emails)")
    e_cols_list = [col[1] for col in c.fetchall()]
    if "is_read" not in e_cols_list:
        c.execute("ALTER TABLE emails ADD COLUMN is_read INTEGER DEFAULT 0")
    if "account_owner" not in e_cols_list:
        c.execute("ALTER TABLE emails ADD COLUMN account_owner TEXT")
    if "attachments_json" not in e_cols_list:
        c.execute("ALTER TABLE emails ADD COLUMN attachments_json TEXT")
    if "dry_run_mode" not in e_cols_list:
        c.execute("ALTER TABLE emails ADD COLUMN dry_run_mode INTEGER DEFAULT 0")
    if "approval_status" not in e_cols_list:
        c.execute("ALTER TABLE emails ADD COLUMN approval_status TEXT DEFAULT 'pending'")  # pending/approved/rejected
    
    # Create Templates Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY,
            name TEXT,
            content TEXT,
            keywords TEXT,
            attachments_json TEXT
        )
    ''')
    
    # Create Settings Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Create Logs Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            action TEXT,
            email_id TEXT,
            detail TEXT
        )
    ''')

    # Create Tasks Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            priority TEXT,
            status TEXT,
            due_date TEXT,
            email_id TEXT,
            created_at TEXT
        )
    ''')

    # Create KB Files Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS kb_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            file_hash TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_modified TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            sync_status TEXT DEFAULT 'pending',
            sync_time TIMESTAMP,
            metadata TEXT
        )
    ''')

    # Create KB File Versions Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS kb_file_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER,
            version INTEGER,
            file_hash TEXT,
            file_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            backup_path TEXT,
            FOREIGN KEY (file_id) REFERENCES kb_files(id)
        )
    ''')

    # Create indexes for KB files
    c.execute("CREATE INDEX IF NOT EXISTS idx_kb_filename ON kb_files(filename)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_kb_file_hash ON kb_files(file_hash)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_kb_sync_status ON kb_files(sync_status)")

    # Migration: Update emails table
    c.execute("PRAGMA table_info(emails)")
    e_cols = [col[1] for col in c.fetchall()]
    new_e_cols = {
        "message_id": "TEXT",
        "thread_id": "TEXT",
        "sent_reply": "TEXT",
        "sent_at": "TEXT"
    }
    for col, dtype in new_e_cols.items():
        if col not in e_cols:
            c.execute(f"ALTER TABLE emails ADD COLUMN {col} {dtype}")
            print(f"Migration: Added {col} column to emails table.")

    # Index for stable deduplication
    c.execute("CREATE INDEX IF NOT EXISTS idx_email_msgid ON emails(message_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_email_uid ON emails(id)")

    # Migration: Update templates table
    c.execute("PRAGMA table_info(templates)")
    t_cols = [col[1] for col in c.fetchall()]
    if "keywords" not in t_cols:
        c.execute("ALTER TABLE templates ADD COLUMN keywords TEXT")
    if "attachments_json" not in t_cols:
        c.execute("ALTER TABLE templates ADD COLUMN attachments_json TEXT")
        print("Migration: Added attachments_json column to templates table.")

    # Migration: Update kb_files table
    c.execute("PRAGMA table_info(kb_files)")
    kb_cols = [col[1] for col in c.fetchall()]
    if "category" not in kb_cols:
        c.execute("ALTER TABLE kb_files ADD COLUMN category TEXT")
        print("Migration: Added category column to kb_files table.")
    if "expiry_date" not in kb_cols:
        c.execute("ALTER TABLE kb_files ADD COLUMN expiry_date TEXT")
        print("Migration: Added expiry_date column to kb_files table.")

    conn.commit()
    conn.close()

def update_kb_file_metadata(file_id, category=None, expiry_date=None):
    """Update user-defined metadata for a KB file."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    
    updates = []
    params = []
    
    if category is not None:
        updates.append("category = ?")
        params.append(category)
        
    if expiry_date is not None:
        updates.append("expiry_date = ?")
        params.append(expiry_date)
        
    if not updates:
        conn.close()
        return False
        
    params.append(file_id)
    query = f"UPDATE kb_files SET {', '.join(updates)} WHERE id = ?"
    
    try:
        c.execute(query, params)
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating KB file metadata: {e}")
        return False
    finally:
        conn.close()


def save_email(email_dict):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    
    msg_id = email_dict.get('message_id')
    uid = email_dict['id']
    owner = email_dict.get('account_owner') # New field
    
    # STABLE DEDUPLICATION: Check by Message-ID and Account-Owner first
    existing = None
    if msg_id and owner:
        c.execute("SELECT id, ai_analysis FROM emails WHERE message_id = ? AND account_owner = ?", (msg_id, owner))
        existing = c.fetchone()
    
    # If not found by Message-ID, try UID and Owner
    if not existing and owner:
        c.execute("SELECT id, ai_analysis FROM emails WHERE id = ? AND account_owner = ?", (uid, owner))
        existing = c.fetchone()
    
    analysis_json = json.dumps(email_dict.get('aiAnalysis')) if email_dict.get('aiAnalysis') else None

    if existing is None:
        c.execute('''
            INSERT INTO emails (id, from_addr, subject, body, received_at, status, ai_analysis, message_id, thread_id, sent_reply, sent_at, is_read, account_owner, attachments_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            uid,
            email_dict['from'],
            email_dict['subject'],
            email_dict['body'],
            email_dict['receivedAt'],
            email_dict['status'],
            analysis_json,
            msg_id,
            email_dict.get('thread_id'),
            email_dict.get('sent_reply'),
            email_dict.get('sent_at'),
            email_dict.get('is_read', 0),
            owner,
            json.dumps(email_dict.get('attachments', []))
        ))
        conn.commit()
        conn.close()
        return True # Added new
    else:
        # SYNC: If the UID changed but it's the same email (Message-ID matched)
        existing_uid = existing[0]
        if existing_uid != uid:
            c.execute("UPDATE emails SET id = ? WHERE message_id = ? AND account_owner = ?", (uid, msg_id, owner))
            print(f"Deduplication: Updated UID from {existing_uid} to {uid} for {msg_id}")
        
        # If we have a sent_reply/at now but didn't before, update it
        if email_dict.get('sent_reply') and not existing[1]:
             c.execute("UPDATE emails SET sent_reply = ?, sent_at = ?, status = ? WHERE id = ? AND account_owner = ?", 
                       (email_dict['sent_reply'], email_dict['sent_at'], 'processed', uid, owner))
        
        conn.commit()
        conn.close()
        return False # Existing

def get_all_emails():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row # Allow access by column name
    c = conn.cursor()
    c.execute("SELECT * FROM emails ORDER BY received_at DESC")
    rows = c.fetchall()
    
    results = []
    for row in rows:
        results.append({
            "id": row['id'],
            "from": row['from_addr'],
            "subject": row['subject'],
            "body": row['body'],
            "receivedAt": row['received_at'],
            "status": row['status'],
            "aiAnalysis": json.loads(row['ai_analysis']) if row['ai_analysis'] else None,
            "message_id": row['message_id'],
            "thread_id": row['thread_id'],
            "sentReply": row['sent_reply'],
            "sentAt": row['sent_at'],
            "isRead": bool(row['is_read']) if 'is_read' in row.keys() else False,
            "accountOwner": row['account_owner'],
            "attachments": json.loads(row['attachments_json']) if row['attachments_json'] else [],
            "dryRunMode": bool(row['dry_run_mode']) if 'dry_run_mode' in row.keys() else False,
            "approvalStatus": row['approval_status'] if 'approval_status' in row.keys() else 'pending'
        })
    conn.close()
    return results

def mark_as_read(email_id):
    """Mark an email as read."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("UPDATE emails SET is_read = 1 WHERE id = ?", (email_id,))
    conn.commit()
    conn.close()

# --- Templates ---
def get_templates():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM templates")
    rows = c.fetchall()
    conn.close()
    return [{
        "id": r["id"], 
        "name": r["name"], 
        "content": r["content"], 
        "keywords": r["keywords"] if r["keywords"] else "",
        "attachments": json.loads(r["attachments_json"]) if r["attachments_json"] else []
    } for r in rows]

def save_template(id, name, content, keywords="", attachments=[]):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO templates (id, name, content, keywords, attachments_json) VALUES (?, ?, ?, ?, ?)", 
              (id, name, content, keywords, json.dumps(attachments)))
    conn.commit()
    conn.close()

def delete_template(id):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("DELETE FROM templates WHERE id = ?", (id,))
    conn.commit()
    conn.close()

# --- Settings ---
def get_settings():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("SELECT * FROM settings")
    rows = c.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def save_setting(key, value):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_bool_setting(key, default=False):
    settings = get_settings()
    val = settings.get(key)
    if val is None: return default
    return str(val).lower() in ('true', '1', 'yes', 'on')

def get_ai_settings():
    """Get AI persona settings with defaults for China Eastern Airlines context."""
    settings = get_settings()
    
    defaults = {
        "ai_persona_org": "China Eastern Airlines Toronto Office",
        "ai_persona_role": "customer service and ticketing support representative",
        "ai_persona_tone": "Professional, efficient, and polite. For complaints, be empathetic and apologetic. For travel agents, serve as a B2B support expert: be concise, use industry codes (PNR, Waiver), and be direct.",
        "ai_persona_examples": """[Example 1: Agent - Waiver Request]
Input: "PNR ABCDEF, flight cancelled, need waiver for full refund."
Reply: "Hi team,\nWaiver code MU/RO/240129/001 issued for PNR ABCDEF due to involuntary cancellation. Please proceed with full refund via BSP/ARC.\nRegards, MU Toronto."

[Example 2: Passenger - Luggage Complaint]
Input: "My luggage is broken! I am very angry!"
Reply: "尊敬的旅客您好，\n非常抱歉听到您的行李在旅途中受损，完全理解这给您带来的不便。\n为了协助您理赔，请提供......我们会根据东航行李运输规定，尽快为您跟进处理。"

[Example 3: Passenger - Policy Query]
Input: "我想把下周三的回国机票改期，要多少钱？"
Reply: "您好，经查询您的票号...目前属于[R]舱。改期费为200 CAD + 票价差额。目前查询同航班差价为50 CAD。预计总费用约为 250 CAD。如需确认改期，请回复确认。" """
    }
    
    # Merge defaults with actual settings
    result = defaults.copy()
    for k, v in settings.items():
        if k in defaults:
            result[k] = v
            
    return result

# --- Logs ---
def get_logs(limit=50):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r["id"], "timestamp": r["timestamp"], "action": r["action"], "emailId": r["email_id"], "detail": r["detail"]} for r in rows]


@safe_db_operation
def log_event(action, email_id, detail):
    with get_db_connection() as conn:
        c = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO logs (timestamp, action, email_id, detail) VALUES (?, ?, ?, ?)", (timestamp, action, email_id, detail))

@safe_db_operation
def update_email_status(email_id, status, analysis=None, sent_reply=None):
    with get_db_connection() as conn:
        c = conn.cursor()
        sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if sent_reply else None
        
        if analysis and sent_reply:
            analysis_json = json.dumps(analysis)
            c.execute("UPDATE emails SET status = ?, ai_analysis = ?, sent_reply = ?, sent_at = ?, dry_run_mode = 0, approval_status = 'sent' WHERE id = ?", (status, analysis_json, sent_reply, sent_at, email_id))
        elif analysis:
            analysis_json = json.dumps(analysis)
            c.execute("UPDATE emails SET status = ?, ai_analysis = ? WHERE id = ?", (status, analysis_json, email_id))
        elif sent_reply:
            c.execute("UPDATE emails SET status = ?, sent_reply = ?, sent_at = ?, dry_run_mode = 0, approval_status = 'sent' WHERE id = ?", (status, sent_reply, sent_at, email_id))
        else:
            # If just updating status to 'processed' (resolved), also clear dry run
            if status == 'processed':
                c.execute("UPDATE emails SET status = ?, dry_run_mode = 0, approval_status = 'resolved' WHERE id = ?", (status, email_id))
            else:
                c.execute("UPDATE emails SET status = ? WHERE id = ?", (status, email_id))

# --- Tasks ---
def get_tasks():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM tasks ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [{
        "id": r["id"],
        "title": r["title"],
        "description": r["description"],
        "priority": r["priority"],
        "status": r["status"],
        "due_date": r["due_date"],
        "email_id": r["email_id"],
        "created_at": r["created_at"]
    } for r in rows]

def save_task(task_dict):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO tasks (title, description, priority, status, due_date, email_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        task_dict['title'],
        task_dict['description'],
        task_dict.get('priority', 'Normal'),
        task_dict.get('status', 'pending'),
        task_dict.get('due_date'),
        task_dict.get('email_id'),
        now
    ))
    conn.commit()
    conn.close()

def update_task_status(task_id, status):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    conn.commit()
    conn.close()

def delete_task(task_id):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def clear_all_emails():
    """Wipe all email and log data but keep templates and settings."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("DELETE FROM emails")
    c.execute("DELETE FROM logs")
    c.execute("DELETE FROM tasks")
    conn.commit()
    conn.close()
    return True

def get_pending_drafts():
    """Get all emails in dry run mode that are pending approval."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM emails 
        WHERE dry_run_mode = 1 AND approval_status = 'pending' AND (status = 'processed' OR status = 'pending_review')
        ORDER BY received_at DESC
    """)
    rows = c.fetchall()
    
    results = []
    for row in rows:
        results.append({
            "id": row['id'],
            "from": row['from_addr'],
            "subject": row['subject'],
            "body": row['body'],
            "receivedAt": row['received_at'],
            "status": row['status'],
            "aiAnalysis": json.loads(row['ai_analysis']) if row['ai_analysis'] else None,
            "sentReply": row['sent_reply'],
            "accountOwner": row['account_owner'],
            "approvalStatus": row['approval_status'],
            "dryRunMode": bool(row['dry_run_mode'])
        })
    
    conn.close()
    return results

def approve_draft(email_id, account_owner):
    """Approve a draft email for sending."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("""
        UPDATE emails 
        SET approval_status = 'approved' 
        WHERE id = ? AND account_owner = ?
    """, (email_id, account_owner))
    conn.commit()
    conn.close()
    return True

def reject_draft(email_id, account_owner):
    """Reject a draft email."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("""
        UPDATE emails 
        SET approval_status = 'rejected', dry_run_mode = 0
        WHERE id = ? AND account_owner = ?
    """, (email_id, account_owner))
    conn.commit()
    conn.close()
    return True

def reset_email(email_id, account_owner):
    """Reset an email to unread/no-analysis state for re-evaluation."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("""
        UPDATE emails 
        SET status = 'unread', 
            ai_analysis = NULL, 
            dry_run_mode = 0, 
            approval_status = 'pending'
        WHERE id = ? AND account_owner = ?
    """, (email_id, account_owner))
    conn.commit()
    conn.close()
    return True

def batch_approve_drafts(email_ids_with_owners):
    """Batch approve multiple drafts. email_ids_with_owners is list of (id, owner) tuples."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    for email_id, owner in email_ids_with_owners:
        c.execute("""
            UPDATE emails 
            SET approval_status = 'approved' 
            WHERE id = ? AND account_owner = ?
        """, (email_id, owner))
    conn.commit()
    conn.close()
    return True

def batch_reject_drafts(email_ids_with_owners):
    """Batch reject multiple drafts."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    for email_id, owner in email_ids_with_owners:
        c.execute("""
            UPDATE emails 
            SET approval_status = 'rejected', dry_run_mode = 0
            WHERE id = ? AND account_owner = ?
        """, (email_id, owner))
    conn.commit()
    conn.close()
    return True

def mark_email_as_dry_run(email_id, account_owner):
    """Mark an email as dry run mode (won't auto-send)."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    c.execute("""
        UPDATE emails 
        SET dry_run_mode = 1, approval_status = 'pending', status = 'processed'
        WHERE id = ? AND account_owner = ?
    """, (email_id, account_owner))
    conn.commit()
    conn.close()
    return True
