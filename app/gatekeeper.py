from typing import Dict, List, Optional, Tuple
from datetime import datetime
from app.config import load_config
from app.database import db_session, log_activity
from app.gmail_client import GmailClient

class GatekeeperEngine:
    def __init__(self, client: Optional[GmailClient] = None):
        self.config = load_config()
        self.client = client or GmailClient()

    def is_sender_allowed(self, sender_email: str, sender_name: str, subject: str) -> Tuple[bool, str]:
        """
        Check if sender or email content matches allowlist rules or VIP patterns.
        """
        sender_email = sender_email.lower().strip()
        full_text = f"{sender_name} {sender_email} {subject}".lower()

        # 1. Check VIP Keywords from config
        for kw in self.config.get("vip_keywords", []):
            if kw.lower() in full_text:
                return True, f"VIP Keyword: '{kw}'"

        # 2. Check Database Allowlist (emails, domains, keywords)
        with db_session() as conn:
            cursor = conn.cursor()
            
            # Exact email or wildcard
            cursor.execute("SELECT pattern, type, reason FROM allowlist")
            rules = cursor.fetchall()

            for pattern, r_type, reason in rules:
                pat = pattern.lower().strip()
                if r_type == "email" and pat == sender_email:
                    return True, f"Allowlisted Email ({reason or pat})"
                elif r_type == "domain" and pat in sender_email:
                    return True, f"Allowlisted Domain ({reason or pat})"
                elif r_type == "keyword" and pat in full_text:
                    return True, f"Allowlisted Keyword: '{pat}' ({reason})"

            # 3. Check senders table action_preference
            cursor.execute("SELECT action_preference FROM senders WHERE email = ?", (sender_email,))
            row = cursor.fetchone()
            if row and row["action_preference"] in ("allowed", "keep"):
                return True, "Sender preference: Allowed"

        return False, "Not in allowlist"

    def is_sender_blocked(self, sender_email: str) -> Tuple[bool, str]:
        """Check if sender is on the blocklist."""
        sender_email = sender_email.lower().strip()
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pattern, type, reason FROM blocklist")
            rules = cursor.fetchall()
            for pattern, r_type, reason in rules:
                pat = pattern.lower().strip()
                if r_type == "email" and pat == sender_email:
                    return True, f"Blocklisted Email: {pat}"
                elif r_type == "domain" and pat in sender_email:
                    return True, f"Blocklisted Domain: {pat}"

            cursor.execute("SELECT action_preference FROM senders WHERE email = ?", (sender_email,))
            row = cursor.fetchone()
            if row and row["action_preference"] in ("blocked", "unsubscribe_and_delete"):
                return True, "Sender marked as Blocked"

        return False, ""

    def process_quarantine_candidate(self, email_meta: Dict) -> bool:
        """
        Evaluates an email. If unknown/unsolicited personal email, moves to Gated folder
        and adds to quarantine queue.
        """
        sender_email = email_meta.get("sender_email", "")
        sender_name = email_meta.get("sender_name", "")
        subject = email_meta.get("subject", "")
        imap_id = email_meta.get("imap_id", "")
        gated_folder = self.config.get("gated_folder", "ZenInbox/Gated")

        # Check blocklist first
        is_blocked, block_reason = self.is_sender_blocked(sender_email)
        if is_blocked:
            self.client.move_messages([imap_id], self.config.get("trash_folder", "[Gmail]/Trash"), source_folder="INBOX")
            log_activity("gatekeeper_block", f"Auto-trashed {sender_email} ({block_reason})")
            return False

        # Check allowlist / VIP
        is_allowed, allow_reason = self.is_sender_allowed(sender_email, sender_name, subject)
        if is_allowed:
            # Star if VIP
            if "VIP" in allow_reason or "Allowlist" in allow_reason:
                self.client.star_messages([imap_id], folder="INBOX")
            return True

        # Unknown Sender -> Gate it!
        moved = self.client.move_messages([imap_id], gated_folder, source_folder="INBOX")
        if moved > 0:
            with db_session() as conn:
                conn.execute("""
                INSERT INTO quarantine_items 
                (imap_id, message_rfc_id, sender_email, sender_name, subject, date, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """, (
                    imap_id,
                    email_meta.get("rfc_id", ""),
                    sender_email,
                    sender_name,
                    subject,
                    email_meta.get("date", ""),
                    datetime.utcnow().isoformat()
                ))
            
            log_activity("gatekeeper_quarantine", f"Quarantined email from {sender_name} <{sender_email}>: '{subject}'")

            # Auto challenge if enabled
            if self.config.get("gatekeeper_auto_challenge", False):
                self.send_challenge(sender_email, subject)

            return False
        return True

    def send_challenge(self, sender_email: str, original_subject: str = ""):
        """Send a polite automated challenge to unknown sender."""
        subj = f"{self.config.get('challenge_subject', 'Attention required: Verify to reach my Priority Inbox')} [Re: {original_subject}]"
        body = self.config.get("challenge_template", "")
        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; max-width: 600px; padding: 24px; border: 1px solid #e2e8f0; border-radius: 10px;">
            <div style="font-size: 20px; font-weight: 700; color: #4f46e5; margin-bottom: 16px;">ZenInbox Gatekeeper</div>
            <p>{body.replace(chr(10), '<br>')}</p>
            <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
            <small style="color: #718096;">Protected by ZenInbox &bull; Safe Email Gatekeeping</small>
        </div>
        """
        try:
            self.client.send_email(to_addr=sender_email, subject=subj, html_content=html, text_content=body)
            log_activity("gatekeeper_challenge", f"Challenge sent to {sender_email}")
        except Exception as e:
            print(f"[Gatekeeper] Failed to send challenge: {e}")

    def approve_item(self, quarantine_id: int) -> bool:
        """Approve a quarantined message, move back to INBOX, and add sender to allowlist."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM quarantine_items WHERE id = ?", (quarantine_id,))
            item = cursor.fetchone()
            if not item:
                return False

            imap_id = item["imap_id"]
            sender_email = item["sender_email"]
            gated_folder = self.config.get("gated_folder", "ZenInbox/Gated")

            # Move from Gated back to INBOX
            self.client.move_messages([imap_id], "INBOX", source_folder=gated_folder)

            # Add sender to allowlist
            cursor.execute("""
            INSERT OR REPLACE INTO allowlist (pattern, type, reason, created_at)
            VALUES (?, 'email', 'Approved from Quarantine', ?)
            """, (sender_email, datetime.utcnow().isoformat()))

            # Update sender preference
            cursor.execute("""
            INSERT INTO senders (email, name, category, action_preference, first_seen, last_seen)
            VALUES (?, ?, 'personal', 'allowed', ?, ?)
            ON CONFLICT(email) DO UPDATE SET action_preference='allowed'
            """, (sender_email, item["sender_name"], datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))

            # Mark item approved
            cursor.execute("UPDATE quarantine_items SET status = 'approved' WHERE id = ?", (quarantine_id,))

        log_activity("gatekeeper_allow", f"Approved {sender_email} and moved email to INBOX")
        return True

    def block_item(self, quarantine_id: int) -> bool:
        """Block a quarantined message, move to Trash, and add sender to blocklist."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM quarantine_items WHERE id = ?", (quarantine_id,))
            item = cursor.fetchone()
            if not item:
                return False

            imap_id = item["imap_id"]
            sender_email = item["sender_email"]
            gated_folder = self.config.get("gated_folder", "ZenInbox/Gated")
            trash_folder = self.config.get("trash_folder", "[Gmail]/Trash")

            # Move to Trash
            self.client.move_messages([imap_id], trash_folder, source_folder=gated_folder)

            # Add to blocklist
            cursor.execute("""
            INSERT OR REPLACE INTO blocklist (pattern, type, reason, created_at)
            VALUES (?, 'email', 'Blocked from Quarantine', ?)
            """, (sender_email, datetime.utcnow().isoformat()))

            # Update sender preference
            cursor.execute("""
            UPDATE senders SET action_preference = 'blocked' WHERE email = ?
            """, (sender_email,))

            cursor.execute("UPDATE quarantine_items SET status = 'blocked' WHERE id = ?", (quarantine_id,))

        log_activity("gatekeeper_block", f"Blocked {sender_email} from quarantine")
        return True
