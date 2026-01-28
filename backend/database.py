import sqlite3
import json
from datetime import datetime

DB_NAME = "mailguard.db"

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

    conn.commit()
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
            INSERT INTO emails (id, from_addr, subject, body, received_at, status, ai_analysis, message_id, thread_id, sent_reply, sent_at, is_read, account_owner)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            owner
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
            "accountOwner": row['account_owner'] # Added
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
        "keywords": r.get("keywords") or "",
        "attachments": json.loads(r["attachments_json"]) if r.get("attachments_json") else []
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

# --- Logs ---
def get_logs(limit=50):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r["id"], "timestamp": r["timestamp"], "action": r["action"], "emailId": r["email_id"], "detail": r["detail"]} for r in rows]

def log_event(action, email_id, detail):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO logs (timestamp, action, email_id, detail) VALUES (?, ?, ?, ?)", (timestamp, action, email_id, detail))
    conn.commit()
    conn.close()

    conn.commit()
    conn.close()

def update_email_status(email_id, status, analysis=None, sent_reply=None):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if sent_reply else None
    
    if analysis and sent_reply:
        analysis_json = json.dumps(analysis)
        c.execute("UPDATE emails SET status = ?, ai_analysis = ?, sent_reply = ?, sent_at = ? WHERE id = ?", (status, analysis_json, sent_reply, sent_at, email_id))
    elif analysis:
        analysis_json = json.dumps(analysis)
        c.execute("UPDATE emails SET status = ?, ai_analysis = ? WHERE id = ?", (status, analysis_json, email_id))
    elif sent_reply:
        c.execute("UPDATE emails SET status = ?, sent_reply = ?, sent_at = ? WHERE id = ?", (status, sent_reply, sent_at, email_id))
    else:
        c.execute("UPDATE emails SET status = ? WHERE id = ?", (status, email_id))
    conn.commit()
    conn.close()

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
