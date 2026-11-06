import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
from app.config import DATA_DIR

DB_PATH = DATA_DIR / "zeninbox.db"

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def db_session():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db_session() as conn:
        cursor = conn.cursor()
        
        # Senders table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS senders (
            email TEXT PRIMARY KEY,
            name TEXT,
            category TEXT DEFAULT 'unknown',
            action_preference TEXT DEFAULT 'keep',
            total_received INTEGER DEFAULT 0,
            total_read INTEGER DEFAULT 0,
            open_rate REAL DEFAULT 0.0,
            first_seen TEXT,
            last_seen TEXT,
            unsubscribe_url TEXT,
            unsubscribe_mailto TEXT,
            unsubscribed_at TEXT,
            clutter_score REAL DEFAULT 0.0,
            notes TEXT
        )
        """)

        # Quarantine items (Gated.com queue)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS quarantine_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imap_id TEXT,
            message_rfc_id TEXT,
            sender_email TEXT,
            sender_name TEXT,
            subject TEXT,
            date TEXT,
            status TEXT DEFAULT 'pending',
            challenge_sent_at TEXT,
            created_at TEXT
        )
        """)

        # Rollup items (Unroll.me digest)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS rollup_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imap_id TEXT,
            sender_email TEXT,
            sender_name TEXT,
            subject TEXT,
            snippet TEXT,
            date TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TEXT
        )
        """)

        # Allowlist (Gatekeeper VIPs & trusted senders)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT UNIQUE,
            type TEXT DEFAULT 'email',
            reason TEXT,
            created_at TEXT
        )
        """)

        # Blocklist (Gatekeeper spammers)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS blocklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT UNIQUE,
            type TEXT DEFAULT 'email',
            reason TEXT,
            created_at TEXT
        )
        """)

        # Activity logs
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            action_type TEXT,
            details TEXT
        )
        """)
        
        # Populate initial VIP allowlist from config if empty
        cursor.execute("SELECT COUNT(*) FROM allowlist")
        if cursor.fetchone()[0] == 0:
            initial_patterns = [
                ("selar", "keyword", "Selar notifications & purchases"),
                ("ileoja", "keyword", "Ileoja platform alerts"),
                ("receipt", "keyword", "Transactional receipts"),
                ("invoice", "keyword", "Billing invoices"),
                ("bank", "keyword", "Banking alerts"),
                ("payment", "keyword", "Payment confirmations")
            ]
            cursor.executemany(
                "INSERT OR IGNORE INTO allowlist (pattern, type, reason, created_at) VALUES (?, ?, ?, ?)",
                [(p, t, r, datetime.utcnow().isoformat()) for p, t, r in initial_patterns]
            )

def log_activity(action_type: str, details: str):
    try:
        with db_session() as conn:
            conn.execute(
                "INSERT INTO activity_logs (timestamp, action_type, details) VALUES (?, ?, ?)",
                (datetime.utcnow().isoformat(), action_type, details)
            )
    except Exception as e:
        print(f"[DB Log Error] {e}")
