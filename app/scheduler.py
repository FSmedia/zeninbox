import threading
import time
from datetime import datetime
from typing import Dict, Optional

from app.config import load_config
from app.gmail_client import GmailClient
from app.gatekeeper import GatekeeperEngine
from app.unroll import UnrollEngine
from app.cleanfox import CleanfoxEngine
from app.database import log_activity, db_session

class ScanManager:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.is_scanning = False
        self.last_scan_time: Optional[str] = None
        self.last_scan_result: Dict = {}
        self._stop_background = False
        self._thread: Optional[threading.Thread] = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ScanManager()
        return cls._instance

    def run_scan(self, limit: int = 500) -> Dict:
        """Execute a full inbox triage scan."""
        with self._lock:
            if self.is_scanning:
                return {"status": "busy", "message": "A scan is already in progress"}
            self.is_scanning = True

        client = GmailClient()
        gatekeeper = GatekeeperEngine(client)
        unroll = UnrollEngine(client)
        cleanfox = CleanfoxEngine(client)

        stats = {
            "scanned": 0,
            "vip_starred": 0,
            "rolled_up": 0,
            "quarantined": 0,
            "trashed": 0,
            "subscriptions_found": 0,
            "status": "success",
            "message": ""
        }

        try:
            print(f"[Scanner] Fetching up to {limit} email headers from INBOX...")
            emails = client.fetch_email_headers_batch(folder="INBOX", limit=limit)
            stats["scanned"] = len(emails)

            if not emails:
                stats["message"] = "Inbox is empty or no messages found."
                return stats

            # 1. Update sender stats and unsubscribe links in DB
            cleanfox.update_sender_stats_from_batch(emails)

            # 2. Process each email according to Gated, Unroll, and Cleanfox rules
            config = load_config()
            gatekeeper_active = config.get("gatekeeper_enabled", True)

            for em in emails:
                s_email = em.get("sender_email", "").lower().strip()
                s_name = em.get("sender_name", "")
                subj = em.get("subject", "")
                imap_id = em.get("imap_id", "")

                # Rule A: Blocked senders -> Trash
                is_blocked, _ = gatekeeper.is_sender_blocked(s_email)
                if is_blocked:
                    client.move_messages([imap_id], config.get("trash_folder", "[Gmail]/Trash"), source_folder="INBOX")
                    stats["trashed"] += 1
                    continue

                # Rule B: Senders in Rollup -> Move to Rollup
                if unroll.process_rollup_message(em):
                    stats["rolled_up"] += 1
                    continue

                # Rule C: VIP / Allowlist -> Star in Inbox
                is_allowed, allow_reason = gatekeeper.is_sender_allowed(s_email, s_name, subj)
                if is_allowed:
                    if "VIP" in allow_reason or "Allowlist" in allow_reason:
                        client.star_messages([imap_id], folder="INBOX")
                        stats["vip_starred"] += 1
                    continue

                # Rule D: Detected Subscriptions -> Keep in Inbox for now, but count
                if em.get("is_subscription"):
                    stats["subscriptions_found"] += 1
                    continue

                # Rule E: Unknown sender -> If Gatekeeper active, move to Gated quarantine!
                if gatekeeper_active:
                    gatekeeper.process_quarantine_candidate(em)
                    stats["quarantined"] += 1

            self.last_scan_time = datetime.now().isoformat()
            stats["message"] = (
                f"Scan complete: Scanned {stats['scanned']} emails. "
                f"VIPs starred: {stats['vip_starred']}, Rolled up: {stats['rolled_up']}, "
                f"Quarantined: {stats['quarantined']}, Trashed: {stats['trashed']}."
            )
            log_activity("scan_completed", stats["message"])
            self.last_scan_result = stats

        except Exception as e:
            stats["status"] = "error"
            stats["message"] = f"Scan error: {str(e)}"
            print(f"[Scanner Error] {e}")
        finally:
            client.close()
            with self._lock:
                self.is_scanning = False

        return stats

    def start_background_loop(self):
        """Starts periodic background sync if enabled in settings."""
        if self._thread and self._thread.is_alive():
            return

        def loop():
            while not self._stop_background:
                conf = load_config()
                if conf.get("auto_sync_enabled", False):
                    interval = max(5, int(conf.get("auto_sync_interval_minutes", 15))) * 60
                    self.run_scan(limit=conf.get("batch_scan_limit", 500))
                    time.sleep(interval)
                else:
                    time.sleep(30)

        self._stop_background = False
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop_background_loop(self):
        self._stop_background = True
