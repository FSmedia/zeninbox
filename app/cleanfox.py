from typing import List, Dict, Optional, Tuple
from datetime import datetime
from app.config import load_config
from app.database import db_session, log_activity
from app.gmail_client import GmailClient

class CleanfoxEngine:
    """
    Subscription Cleaner & Inbox Health Engine.
    Handles engagement metrics, open rate analysis, 1-click RFC unsubscribe,
    and Keep Newest Edition Only (pruning stale backlogged issues).
    """
    def __init__(self, client: Optional[GmailClient] = None):
        self.config = load_config()
        self.client = client or GmailClient()

    def update_sender_stats_from_batch(self, emails: List[Dict]):
        """
        Takes raw batch of scanned emails, aggregates counts, read rates,
        unsubscribe links, and upserts into the senders table.
        """
        sender_buckets: Dict[str, Dict] = {}

        for em in emails:
            addr = em.get("sender_email", "").lower().strip()
            if not addr:
                continue

            if addr not in sender_buckets:
                sender_buckets[addr] = {
                    "email": addr,
                    "name": em.get("sender_name") or addr,
                    "is_subscription": em.get("is_subscription", False),
                    "total": 0,
                    "read": 0,
                    "http_unsub": em.get("http_unsub"),
                    "mailto_unsub": em.get("mailto_unsub"),
                    "is_one_click": em.get("is_one_click", False),
                    "last_date": em.get("date", "")
                }
            bucket = sender_buckets[addr]
            bucket["total"] += 1
            if em.get("is_read"):
                bucket["read"] += 1
            if em.get("http_unsub") and not bucket["http_unsub"]:
                bucket["http_unsub"] = em["http_unsub"]
            if em.get("mailto_unsub") and not bucket["mailto_unsub"]:
                bucket["mailto_unsub"] = em["mailto_unsub"]
            if em.get("is_subscription"):
                bucket["is_subscription"] = True

        # Now save to SQLite
        with db_session() as conn:
            cursor = conn.cursor()
            for addr, data in sender_buckets.items():
                open_rate = round(data["read"] / data["total"], 2) if data["total"] > 0 else 0.0
                
                # Clutter calculation: high volume + low open rate = max clutter
                unread_count = data["total"] - data["read"]
                clutter_score = round(min(100.0, (unread_count * 15.0) * (1.0 - open_rate + 0.1)), 1)
                
                cursor.execute("""
                INSERT INTO senders (
                    email, name, category, total_received, total_read, open_rate, 
                    first_seen, last_seen, unsubscribe_url, unsubscribe_mailto, clutter_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    total_received = total_received + excluded.total_received,
                    total_read = total_read + excluded.total_read,
                    open_rate = ROUND(CAST(total_read + excluded.total_read AS REAL) / (total_received + excluded.total_received), 2),
                    last_seen = excluded.last_seen,
                    unsubscribe_url = COALESCE(excluded.unsubscribe_url, senders.unsubscribe_url),
                    unsubscribe_mailto = COALESCE(excluded.unsubscribe_mailto, senders.unsubscribe_mailto),
                    clutter_score = excluded.clutter_score
                """, (
                    addr,
                    data["name"],
                    "subscription" if data["is_subscription"] else "unknown",
                    data["total"],
                    data["read"],
                    open_rate,
                    datetime.utcnow().isoformat(),
                    data["last_date"],
                    data["http_unsub"],
                    data["mailto_unsub"],
                    clutter_score
                ))

    def prune_older_editions(self, sender_email: str, keep_count: int = 1) -> Dict:
        """
        FEATURE: Keep Newest Edition Only.
        Keeps the single most recent email in the inbox, and moves all
        older stale issues from this sender directly to Trash.
        """
        sender_email = sender_email.lower().strip()
        trash_folder = self.config.get("trash_folder", "[Gmail]/Trash")
        result = {
            "email": sender_email,
            "kept": 0,
            "pruned_to_trash": 0,
            "status": "success"
        }

        try:
            imap = self.client.connect_imap()
            status, _ = imap.select("INBOX")
            if status == "OK":
                search_q = f'FROM "{sender_email}"'
                status, s_data = imap.search(None, search_q)
                if status == "OK" and s_data[0]:
                    all_ids = s_data[0].split()
                    total_found = len(all_ids)
                    if total_found > keep_count:
                        # Gmail sequence IDs increase chronologically; highest ID = newest message
                        # Keep the latest `keep_count`
                        older_ids = [x.decode() for x in all_ids[:-keep_count]]
                        pruned_count = self.client.move_messages(older_ids, trash_folder, source_folder="INBOX")
                        result["pruned_to_trash"] = pruned_count
                        result["kept"] = keep_count
                    else:
                        result["kept"] = total_found
                        result["pruned_to_trash"] = 0
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            print(f"[Prune Error] {e}")

        # Update sender preference to keep_newest_only
        with db_session() as conn:
            conn.execute("""
            UPDATE senders 
            SET action_preference = 'keep_newest_only'
            WHERE email = ?
            """, (sender_email,))

        log_activity(
            "pruned_older_editions",
            f"Kept newest edition of {sender_email}; purged {result['pruned_to_trash']} older backlogged issues to Trash."
        )

        return result

    def prune_all_subscriptions(self, keep_count: int = 1) -> Dict:
        """
        Batch 1-Click Action: Prune older backlogged editions across ALL active subscriptions,
        keeping only the single freshest issue of each.
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT email FROM senders 
            WHERE category = 'subscription' 
              AND action_preference NOT IN ('unsubscribe_and_delete', 'blocked')
              AND total_received > ?
            """, (keep_count,))
            senders = [r["email"] for r in cursor.fetchall()]

        total_pruned = 0
        senders_processed = 0

        for s_email in senders:
            res = self.prune_older_editions(s_email, keep_count=keep_count)
            total_pruned += res.get("pruned_to_trash", 0)
            senders_processed += 1

        return {
            "status": "success",
            "senders_processed": senders_processed,
            "total_older_emails_pruned": total_pruned
        }

    def unsubscribe_and_delete_sender(self, sender_email: str) -> Dict:
        """
        Core Action:
        1. Fire RFC 8058 / RFC 2369 unsubscribe request.
        2. Move ALL past emails from this sender in INBOX to Trash.
        3. Block future emails.
        """
        sender_email = sender_email.lower().strip()
        trash_folder = self.config.get("trash_folder", "[Gmail]/Trash")
        result = {
            "email": sender_email,
            "unsubscribed": False,
            "unsub_message": "",
            "messages_deleted": 0
        }

        # 1. Fetch sender info from DB
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM senders WHERE email = ?", (sender_email,))
            sender = cursor.fetchone()

        http_unsub = sender["unsubscribe_url"] if sender else None
        mailto_unsub = sender["unsubscribe_mailto"] if sender else None

        # 2. Trigger Unsubscribe
        if http_unsub or mailto_unsub:
            success, msg = self.client.trigger_one_click_unsubscribe(
                http_url=http_unsub,
                mailto_url=mailto_unsub,
                is_one_click=True
            )
            result["unsubscribed"] = success
            result["unsub_message"] = msg
        else:
            result["unsub_message"] = "No direct List-Unsubscribe header, blocked future mail."

        # 3. Search and Trash all messages from sender in INBOX
        try:
            imap = self.client.connect_imap()
            status, _ = imap.select("INBOX")
            if status == "OK":
                search_q = f'FROM "{sender_email}"'
                status, s_data = imap.search(None, search_q)
                if status == "OK" and s_data[0]:
                    ids_to_trash = [x.decode() for x in s_data[0].split()]
                    deleted_count = self.client.move_messages(ids_to_trash, trash_folder, source_folder="INBOX")
                    result["messages_deleted"] = deleted_count
        except Exception as e:
            print(f"[Cleaner] Error moving past emails to trash: {e}")

        # 4. Mark sender in DB as unsubscribed & blocked
        with db_session() as conn:
            conn.execute("""
            UPDATE senders 
            SET action_preference = 'unsubscribe_and_delete',
                unsubscribed_at = ?
            WHERE email = ?
            """, (datetime.utcnow().isoformat(), sender_email))

            # Add to blocklist
            conn.execute("""
            INSERT OR REPLACE INTO blocklist (pattern, type, reason, created_at)
            VALUES (?, 'email', 'Unsubscribed & Deleted via Cleaner', ?)
            """, (sender_email, datetime.utcnow().isoformat()))

        log_activity(
            "unsubscribed",
            f"Unsubscribed from {sender_email} ({result['unsub_message']}) & deleted {result['messages_deleted']} emails."
        )

        return result

    def get_inbox_health_stats(self) -> Dict:
        """
        Returns clean inbox health metrics.
        """
        with db_session() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM senders")
            total_senders = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM senders WHERE category = 'subscription'")
            total_subscriptions = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM senders WHERE action_preference = 'rollup'")
            total_rollups = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM senders WHERE action_preference = 'keep_newest_only'")
            total_kept_newest = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM senders WHERE action_preference = 'unsubscribe_and_delete'")
            total_unsubscribed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM quarantine_items WHERE status = 'pending'")
            pending_quarantine = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(total_received), SUM(total_read) FROM senders")
            row = cursor.fetchone()
            total_emails = row[0] or 0
            total_read = row[1] or 0

        # Clean score calculation
        open_pct = (total_read / total_emails * 100) if total_emails > 0 else 85.0
        health_score = min(100, max(20, int(open_pct * 0.6 + (total_unsubscribed + total_rollups + total_kept_newest) * 2)))

        # Carbon estimation: average email storage ~ 10g CO2 per 100 emails cleaned
        co2_saved_grams = total_unsubscribed * 45 + total_rollups * 15 + total_kept_newest * 25

        return {
            "total_senders": total_senders,
            "total_subscriptions": total_subscriptions,
            "total_rollups": total_rollups,
            "total_kept_newest": total_kept_newest,
            "total_unsubscribed": total_unsubscribed,
            "pending_quarantine": pending_quarantine,
            "total_emails_tracked": total_emails,
            "health_score": health_score,
            "co2_saved_grams": co2_saved_grams
        }
