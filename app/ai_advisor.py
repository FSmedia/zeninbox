import re
from typing import List, Dict, Optional
from datetime import datetime
from app.database import db_session, log_activity
from app.config import load_config

class AIAdvisorEngine:
    """
    Intelligent AI Email Advisor.
    Analyzes sender volume, open rates, frequency, headers, and subjects
    to generate high-confidence actionable recommendations for inbox purification.
    """
    def __init__(self):
        self.config = load_config()

    def generate_recommendations(self) -> List[Dict]:
        """
        Scan all tracked senders and generate structured recommendations.
        """
        recommendations = []

        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT email, name, category, total_received, total_read, open_rate, 
                   action_preference, unsubscribe_url, unsubscribe_mailto, clutter_score, last_seen
            FROM senders
            ORDER BY clutter_score DESC, total_received DESC
            """)
            senders = [dict(r) for r in cursor.fetchall()]

        vip_keywords = [k.lower() for k in self.config.get("vip_keywords", [])]

        for s in senders:
            email_addr = s["email"].lower()
            name = s["name"] or email_addr
            total = s["total_received"]
            open_rate = s["open_rate"] or 0.0
            pref = s["action_preference"]

            # Skip already handled/unsubscribed senders
            if pref in ("unsubscribe_and_delete", "blocked"):
                continue

            full_desc = f"{name} {email_addr}".lower()

            # Rule 1: VIP Financial / Critical Transactions
            is_vip = any(kw in full_desc for kw in vip_keywords)
            if is_vip and pref != "allowed":
                recommendations.append({
                    "id": f"rec_{email_addr}",
                    "email": email_addr,
                    "name": name,
                    "category": "VIP / Transactional",
                    "action": "vip_whitelist",
                    "action_label": "Whitelist & Star as VIP",
                    "confidence": 98,
                    "badge_color": "emerald",
                    "reason": f"Matches critical financial or platform patterns ({', '.join([k for k in vip_keywords if k in full_desc])}). Direct delivery & star recommended.",
                    "total_emails": total,
                    "open_rate": open_rate
                })
                continue

            # Rule 2: Inactive/Dead Newsletter (high volume, zero or very low opens)
            if total >= 3 and open_rate <= 0.10:
                recommendations.append({
                    "id": f"rec_{email_addr}",
                    "email": email_addr,
                    "name": name,
                    "category": "Inactive Newsletter",
                    "action": "unsubscribe_and_delete",
                    "action_label": "Unsubscribe & Purge All",
                    "confidence": 95 if open_rate == 0 else 88,
                    "badge_color": "rose",
                    "reason": f"Received {total} emails with only {int(open_rate * 100)}% opened. Unsubscribing and purging will eliminate clutter.",
                    "total_emails": total,
                    "open_rate": open_rate
                })
                continue

            # Rule 3: Frequent Newsletter with Backlog (moderate open rate or high volume)
            # Perfect candidate for "Keep Newest Edition Only"
            if total >= 4 and 0.10 < open_rate <= 0.40:
                recommendations.append({
                    "id": f"rec_{email_addr}",
                    "email": email_addr,
                    "name": name,
                    "category": "Backlogged Newsletter",
                    "action": "keep_newest_only",
                    "action_label": "Keep Newest Edition Only",
                    "confidence": 92,
                    "badge_color": "amber",
                    "reason": f"Frequent newsletter ({total} issues received). Keep only the single newest issue fresh and auto-purge stale older editions.",
                    "total_emails": total,
                    "open_rate": open_rate
                })
                continue

            # Rule 4: Informational Subscriptions (reads occasionally, cluttering daily flow)
            if s["category"] == "subscription" and pref != "rollup" and open_rate > 0.40 and total >= 3:
                recommendations.append({
                    "id": f"rec_{email_addr}",
                    "email": email_addr,
                    "name": name,
                    "category": "Daily Digest Candidate",
                    "action": "rollup",
                    "action_label": "Move to Daily Digest",
                    "confidence": 86,
                    "badge_color": "purple",
                    "reason": f"Active newsletter ({int(open_rate * 100)}% open rate). Bundle into your Daily Digest to keep your primary inbox distraction-free.",
                    "total_emails": total,
                    "open_rate": open_rate
                })
                continue

        # Sort recommendations by highest confidence and volume
        recommendations.sort(key=lambda r: (r["confidence"], r["total_emails"]), reverse=True)
        return recommendations

    def execute_recommendation(self, email_addr: str, action: str) -> Dict:
        """
        Execute an AI recommendation for a specific sender.
        """
        from app.cleanfox import CleanfoxEngine
        from app.unroll import UnrollEngine
        from app.gatekeeper import GatekeeperEngine

        cleaner = CleanfoxEngine()
        digest = UnrollEngine()
        screening = GatekeeperEngine()

        email_addr = email_addr.lower().strip()

        if action == "unsubscribe_and_delete":
            res = cleaner.unsubscribe_and_delete_sender(email_addr)
            return {"status": "success", "action": "unsubscribed_and_deleted", "details": res}
        elif action == "keep_newest_only":
            res = cleaner.prune_older_editions(email_addr, keep_count=1)
            return {"status": "success", "action": "kept_newest_only", "details": res}
        elif action == "rollup":
            digest.add_to_rollup(email_addr)
            return {"status": "success", "action": "moved_to_digest", "details": f"Added {email_addr} to Daily Digest"}
        elif action == "vip_whitelist":
            with db_session() as conn:
                conn.execute("""
                INSERT OR REPLACE INTO allowlist (pattern, type, reason, created_at)
                VALUES (?, 'email', 'AI Advisor: VIP financial/critical sender', ?)
                """, (email_addr, datetime.utcnow().isoformat()))
                conn.execute("UPDATE senders SET action_preference = 'allowed' WHERE email = ?", (email_addr,))
            log_activity("ai_vip_whitelist", f"AI Whitelisted {email_addr} as VIP.")
            return {"status": "success", "action": "vip_whitelisted", "details": f"Whitelisted {email_addr} as VIP"}
        elif action == "keep":
            digest.remove_from_rollup(email_addr)
            return {"status": "success", "action": "kept_in_inbox", "details": f"Restored {email_addr} to Inbox"}
        
        return {"status": "error", "message": f"Unknown action: {action}"}

    def execute_all_recommendations(self, max_confidence: int = 80) -> Dict:
        """
        1-Click Execute: Apply all high-confidence AI recommendations across entire inbox.
        """
        recs = self.generate_recommendations()
        applied = []
        errors = []

        for r in recs:
            if r["confidence"] >= max_confidence:
                try:
                    res = self.execute_recommendation(r["email"], r["action"])
                    applied.append({
                        "email": r["email"],
                        "action": r["action"],
                        "result": res
                    })
                except Exception as e:
                    errors.append({"email": r["email"], "error": str(e)})

        log_activity("ai_batch_applied", f"AI Advisor applied {len(applied)} automated inbox recommendations.")

        return {
            "total_applied": len(applied),
            "total_errors": len(errors),
            "applied": applied,
            "errors": errors
        }
