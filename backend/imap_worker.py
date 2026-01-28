import os
import time
import threading
import requests
from imap_tools import MailBox, AND
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path="../.env")

IMAP_SERVER = os.getenv("IMAP_SERVER")
BACKEND_URL = "http://localhost:8010"

def get_all_accounts():
    """Returns a list of {user, password} dicts from .env"""
    accounts = []
    multi = os.getenv("EMAIL_ACCOUNTS")
    if multi:
        for item in multi.split(","):
            if ":" in item:
                u, p = item.split(":", 1)
                accounts.append({"user": u.strip(), "pass": p.strip()})
    
    email_account = os.getenv("EMAIL_ACCOUNT")
    email_password = os.getenv("EMAIL_PASSWORD")
    if email_account and email_password:
        if not any(a['user'] == email_account for a in accounts):
            accounts.append({"user": email_account, "pass": email_password})
            
    return accounts

def listen_to_account(user, password):
    print(f"[*] Starting IMAP IDLE for {user}...")
    while True:
        try:
            with MailBox(IMAP_SERVER).login(user, password) as mailbox:
                print(f"[+] {user} connected and idling...")
                while True:
                    # Wait for changes in the mailbox
                    responses = mailbox.idle.wait(timeout=600) # 10 minutes timeout
                    if responses:
                        print(f"[!] {user}: New activity detected!")
                        # Trigger poll-emails on the main backend
                        try:
                            # Use unread mode to be efficient
                            res = requests.post(f"{BACKEND_URL}/poll-emails?fetch_mode=unread")
                            if res.status_code == 200:
                                data = res.json()
                                print(f"[√] {user}: Poll triggered. New emails: {data.get('new_emails_count', 0)}")
                                
                                # If there are new emails, and auto-process is needed, we could trigger it here
                                # But currently process-emails is a frontend-driven action.
                                # To make it truly automatic, we should add an auto-process endpoint.
                                if data.get('new_emails_count', 0) > 0:
                                    requests.post(f"{BACKEND_URL}/auto-trigger-processing")
                            else:
                                print(f"[×] {user}: Poll failed with status {res.status_code}")
                        except Exception as e:
                            print(f"[×] {user}: Error triggering poll: {e}")
                    else:
                        # Timeout reached, keep-alive
                        print(f"[*] {user}: Idle timeout/Keep-alive")
        except Exception as e:
            print(f"[!] {user}: Connection error: {e}. Retrying in 30s...")
            time.sleep(30)

def main():
    accounts = get_all_accounts()
    if not accounts:
        print("[×] No accounts found. Worker exiting.")
        return

    threads = []
    for acc in accounts:
        t = threading.Thread(target=listen_to_account, args=(acc['user'], acc['pass']), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(1) # Stagger connections

    print(f"[*] Worker started with {len(threads)} threads.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[*] Worker stopping...")

if __name__ == "__main__":
    main()
