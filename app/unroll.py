from typing import List, Dict, Optional, Tuple
from datetime import datetime
from app.config import load_config
from app.database import db_session, log_activity
from app.gmail_client import GmailClient

class UnrollEngine:
    def __init__(self, client: Optional[GmailClient] = None):
        self.config = load_config()
        self.client = client or GmailClient()

    def add_to_rollup(self, sender_email: str) -> bool:
        """Mark a sender to be automatically included in the Daily Rollup."""
        sender_email = sender_email.lower().strip()
        with db_session() as conn:
            conn.execute("""
            UPDATE senders 
            SET action_preference = 'rollup' 
            WHERE email = ?
            """, (sender_email,))
        log_activity("rollup_rule", f"Sender {sender_email} added to Daily Rollup")
        return True

    def remove_from_rollup(self, sender_email: str) -> bool:
        """Remove sender from rollup and return to normal inbox delivery."""
        sender_email = sender_email.lower().strip()
        with db_session() as conn:
            conn.execute("""
            UPDATE senders 
            SET action_preference = 'keep' 
            WHERE email = ?
            """, (sender_email,))
        log_activity("rollup_rule", f"Sender {sender_email} restored to Inbox")
        return True

    def process_rollup_message(self, email_meta: Dict) -> bool:
        """
        If sender is configured for Rollup, move message to Rollup folder
        and record in rollup_items.
        """
        sender_email = email_meta.get("sender_email", "").lower().strip()
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT action_preference FROM senders WHERE email = ?", (sender_email,))
            row = cursor.fetchone()
            if not row or row["action_preference"] != "rollup":
                return False

            imap_id = email_meta.get("imap_id", "")
            rollup_folder = self.config.get("rollup_folder", "ZenInbox/Rollup")

            # Move from INBOX to Rollup folder
            moved = self.client.move_messages([imap_id], rollup_folder, source_folder="INBOX")
            if moved > 0:
                conn.execute("""
                INSERT INTO rollup_items 
                (imap_id, sender_email, sender_name, subject, snippet, date, is_read, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """, (
                    imap_id,
                    sender_email,
                    email_meta.get("sender_name", ""),
                    email_meta.get("subject", ""),
                    email_meta.get("subject", "")[:120],  # subject snippet
                    email_meta.get("date", ""),
                    datetime.utcnow().isoformat()
                ))
                log_activity("rollup_archived", f"Rolled up email from {sender_email}: '{email_meta.get('subject')}'")
                return True

        return False

    def generate_digest_html(self, items: List[Dict]) -> str:
        """Generate a beautiful Unroll.me-style HTML digest."""
        if not items:
            return "<p>No rollup emails today. Your inbox is serene!</p>"

        today_str = datetime.now().strftime("%A, %B %d, %Y")
        cards_html = ""
        for it in items:
            cards_html += f"""
            <tr style="border-bottom: 1px solid #edf2f7;">
                <td style="padding: 16px 8px;">
                    <div style="font-weight: 600; color: #1a202c; font-size: 15px;">{it['sender_name'] or it['sender_email']}</div>
                    <div style="font-size: 14px; color: #4a5568; margin-top: 4px;">{it['subject']}</div>
                    <div style="font-size: 12px; color: #a0aec0; margin-top: 4px;">{it['date']}</div>
                </td>
            </tr>
            """

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Your ZenInbox Daily Rollup</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f7fafc; margin: 0; padding: 24px;">
            <div style="max-width: 650px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 32px 24px; color: #ffffff;">
                    <h1 style="margin: 0; font-size: 24px; font-weight: 700;">ZenInbox Daily Rollup</h1>
                    <p style="margin: 6px 0 0; opacity: 0.9; font-size: 14px;">{today_str} &bull; {len(items)} subscriptions summarized</p>
                </div>
                <div style="padding: 24px;">
                    <table style="width: 100%; border-collapse: collapse;">
                        {cards_html}
                    </table>
                </div>
                <div style="background: #f8fafc; padding: 16px 24px; text-align: center; font-size: 13px; color: #718096; border-top: 1px solid #e2e8f0;">
                    ZenInbox &bull; Unclutter your mind and your inbox
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def send_daily_digest(self) -> Tuple[bool, str]:
        """Compile today's rollup items and send as an aggregated email to user."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM rollup_items 
            WHERE is_read = 0 
            ORDER BY id DESC LIMIT 50
            """)
            items = [dict(r) for r in cursor.fetchall()]

        if not items:
            return False, "No new rollup messages to include in digest."

        html = self.generate_digest_html(items)
        user_email = self.config.get("gmail_user", "")
        subject = f"Your ZenInbox Rollup Digest - {datetime.now().strftime('%b %d')} ({len(items)} items)"

        try:
            self.client.send_email(
                to_addr=user_email,
                subject=subject,
                html_content=html,
                text_content=f"You have {len(items)} rolled-up subscription emails waiting in ZenInbox."
            )
            # Mark them as digested
            with db_session() as conn:
                item_ids = [it["id"] for it in items]
                conn.execute(f"UPDATE rollup_items SET is_read = 1 WHERE id IN ({','.join('?'*len(item_ids))})", item_ids)

            log_activity("rollup_digest_sent", f"Sent daily rollup digest with {len(items)} items to {user_email}")
            return True, f"Rollup digest with {len(items)} newsletters sent to {user_email}!"
        except Exception as e:
            return False, f"Failed to send rollup digest: {str(e)}"
