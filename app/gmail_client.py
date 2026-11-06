import imaplib
import smtplib
import email
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re
import requests
from typing import List, Dict, Tuple, Optional
from datetime import datetime

from app.config import load_config

def decode_rfc_header(header_value: Optional[str]) -> str:
    """Safely decode RFC 2047 email headers (Subject, From, etc.)."""
    if not header_value:
        return ""
    try:
        decoded_fragments = decode_header(header_value)
        result = []
        for fragment, charset in decoded_fragments:
            if isinstance(fragment, bytes):
                charset = charset or "utf-8"
                try:
                    result.append(fragment.decode(charset, errors="replace"))
                except Exception:
                    result.append(fragment.decode("utf-8", errors="replace"))
            else:
                result.append(str(fragment))
        return " ".join(result).strip()
    except Exception:
        return str(header_value).strip()

def parse_sender_info(from_header: str) -> Tuple[str, str]:
    """Extract (name, email) from a From header string."""
    if not from_header:
        return "", ""
    decoded = decode_rfc_header(from_header)
    match = re.search(r"^(.*?)\s*<([^>]+)>$", decoded)
    if match:
        name = match.group(1).strip(' "\'')
        addr = match.group(2).lower().strip()
        return name, addr
    # Just an email address or single token
    clean = decoded.strip(' "\'').lower()
    return clean, clean

def extract_unsubscribe_links(msg: email.message.Message) -> Tuple[Optional[str], Optional[str], bool]:
    """
    Extract (http_url, mailto_url, is_one_click) from List-Unsubscribe headers.
    RFC 2369 / RFC 8058 compliant.
    """
    header = msg.get("List-Unsubscribe", "")
    post_header = msg.get("List-Unsubscribe-Post", "")
    is_one_click = "List-Unsubscribe=One-Click" in post_header

    http_url = None
    mailto_url = None

    if header:
        urls = re.findall(r"<([^>]+)>", header)
        for u in urls:
            u_clean = u.strip()
            if u_clean.lower().startswith("http://") or u_clean.lower().startswith("https://"):
                if not http_url:
                    http_url = u_clean
            elif u_clean.lower().startswith("mailto:"):
                if not mailto_url:
                    mailto_url = u_clean

    return http_url, mailto_url, is_one_click

class GmailClient:
    def __init__(self, user: Optional[str] = None, password: Optional[str] = None):
        config = load_config()
        self.user = user or config.get("gmail_user", "")
        self.password = (password or config.get("gmail_app_password", "")).replace(" ", "")
        self.imap_server = config.get("imap_server", "imap.gmail.com")
        self.imap_port = int(config.get("imap_port", 993))
        self.smtp_server = config.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = int(config.get("smtp_port", 465))
        self.imap: Optional[imaplib.IMAP4_SSL] = None

    def connect_imap(self) -> imaplib.IMAP4_SSL:
        if self.imap is not None:
            try:
                self.imap.noop()
                return self.imap
            except Exception:
                self.imap = None

        self.imap = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
        self.imap.login(self.user, self.password)
        self._ensure_folders()
        return self.imap

    def _ensure_folders(self):
        """Ensure ZenInbox folders exist in Gmail."""
        config = load_config()
        folders_to_check = [config.get("gated_folder", "ZenInbox/Gated"), config.get("rollup_folder", "ZenInbox/Rollup")]
        try:
            status, folder_list = self.imap.list()
            if status == "OK" and folder_list:
                existing = [f.decode(errors="replace") for f in folder_list]
                for f_name in folders_to_check:
                    # Check if folder is present
                    found = any(f'"{f_name}"' in item or f' {f_name}' in item for item in existing)
                    if not found:
                        try:
                            self.imap.create(f'"{f_name}"')
                        except Exception:
                            pass
        except Exception as e:
            print(f"[IMAP] Notice when checking folders: {e}")

    def test_connection(self) -> Tuple[bool, str]:
        """Test IMAP and SMTP login credentials."""
        try:
            imap = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            imap.login(self.user, self.password)
            imap.logout()
            return True, "Successfully connected to Gmail IMAP!"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def get_inbox_count(self) -> int:
        imap = self.connect_imap()
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            return 0
        status, search_data = imap.search(None, "ALL")
        if status == "OK" and search_data[0]:
            return len(search_data[0].split())
        return 0

    def fetch_email_headers_batch(self, folder="INBOX", limit=1000) -> List[Dict]:
        """
        Fetch headers for the latest 'limit' messages in folder.
        Returns detailed parsed metadata (sender, subject, flags, list headers, etc.)
        """
        imap = self.connect_imap()
        status, _ = imap.select(f'"{folder}"' if " " in folder else folder, readonly=True)
        if status != "OK":
            return []

        status, search_data = imap.search(None, "ALL")
        if status != "OK" or not search_data[0]:
            return []

        all_ids = search_data[0].split()
        target_ids = all_ids[-limit:] if len(all_ids) > limit else all_ids
        target_ids.reverse()  # Newest first

        emails = []
        batch_size = 50

        for i in range(0, len(target_ids), batch_size):
            chunk = target_ids[i:i + batch_size]
            chunk_str = b",".join(chunk)
            try:
                res, data = imap.fetch(
                    chunk_str,
                    "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID LIST-UNSUBSCRIBE LIST-UNSUBSCRIBE-POST LIST-ID PRECEDENCE)])"
                )
                if res != "OK" or not data:
                    continue

                for item in data:
                    if not isinstance(item, tuple) or len(item) < 2:
                        continue
                    
                    header_line = item[0].decode(errors="replace")
                    match = re.search(r"^(\d+)\s+", header_line)
                    if not match:
                        continue
                    msg_id = match.group(1)

                    # Check flags (e.g. \Seen, \Flagged)
                    is_read = r"\Seen" in header_line
                    is_starred = r"\Flagged" in header_line

                    msg = email.message_from_bytes(item[1])
                    raw_from = msg.get("From", "")
                    sender_name, sender_email = parse_sender_info(raw_from)
                    subject = decode_rfc_header(msg.get("Subject", "(No Subject)"))
                    date_hdr = decode_rfc_header(msg.get("Date", ""))
                    rfc_id = msg.get("Message-ID", "")
                    
                    # Unsubscribe metadata
                    http_unsub, mailto_unsub, is_one_click = extract_unsubscribe_links(msg)
                    list_id = msg.get("List-ID", "")
                    precedence = str(msg.get("Precedence", "")).lower()

                    is_subscription = bool(http_unsub or mailto_unsub or list_id or "bulk" in precedence or "list" in precedence)

                    emails.append({
                        "imap_id": msg_id,
                        "rfc_id": rfc_id,
                        "sender_name": sender_name or sender_email,
                        "sender_email": sender_email,
                        "subject": subject,
                        "date": date_hdr,
                        "is_read": is_read,
                        "is_starred": is_starred,
                        "is_subscription": is_subscription,
                        "http_unsub": http_unsub,
                        "mailto_unsub": mailto_unsub,
                        "is_one_click": is_one_click,
                        "list_id": list_id
                    })
            except Exception as e:
                print(f"[IMAP Batch Fetch Error] {e}")
                continue

        return emails

    def move_messages(self, imap_ids: List[str], target_folder: str, source_folder="INBOX") -> int:
        """Move given message IDs from source_folder to target_folder."""
        if not imap_ids:
            return 0
        imap = self.connect_imap()
        status, _ = imap.select(f'"{source_folder}"' if " " in source_folder else source_folder)
        if status != "OK":
            return 0

        target_quoted = f'"{target_folder}"' if " " in target_folder else target_folder
        moved_count = 0
        chunk_size = 50

        for i in range(0, len(imap_ids), chunk_size):
            chunk = [str(x).encode() for x in imap_ids[i:i + chunk_size]]
            chunk_bytes = b",".join(chunk)
            try:
                res, _ = imap.copy(chunk_bytes, target_quoted)
                if res == "OK":
                    imap.store(chunk_bytes, "+FLAGS", r"(\Deleted)")
                    moved_count += len(chunk)
            except Exception as e:
                print(f"[IMAP Move Error] {e}")

        if moved_count > 0:
            try:
                imap.expunge()
            except Exception:
                pass

        return moved_count

    def star_messages(self, imap_ids: List[str], folder="INBOX") -> int:
        """Star/Flag messages as VIP."""
        if not imap_ids:
            return 0
        imap = self.connect_imap()
        status, _ = imap.select(f'"{folder}"' if " " in folder else folder)
        if status != "OK":
            return 0

        chunk_size = 50
        flagged = 0
        for i in range(0, len(imap_ids), chunk_size):
            chunk = [str(x).encode() for x in imap_ids[i:i + chunk_size]]
            chunk_bytes = b",".join(chunk)
            try:
                res, _ = imap.store(chunk_bytes, "+FLAGS", r"(\Flagged)")
                if res == "OK":
                    flagged += len(chunk)
            except Exception as e:
                print(f"[IMAP Star Error] {e}")
        return flagged

    def send_email(self, to_addr: str, subject: str, html_content: str, text_content: Optional[str] = None):
        """Send an email via Gmail SMTP (for Challenges or Daily Rollup digests)."""
        msg = MIMEMultipart("alternative")
        msg["From"] = f"ZenInbox <{self.user}>"
        msg["To"] = to_addr
        msg["Subject"] = subject

        if text_content:
            msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
            server.login(self.user, self.password)
            server.sendmail(self.user, [to_addr], msg.as_string())

    def trigger_one_click_unsubscribe(self, http_url: Optional[str], mailto_url: Optional[str], is_one_click: bool = False) -> Tuple[bool, str]:
        """
        Executes RFC 8058 or RFC 2369 one-click unsubscribe request.
        """
        if http_url:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                }
                if is_one_click:
                    # RFC 8058 specifies a POST request with body: List-Unsubscribe=One-Click
                    resp = requests.post(
                        http_url,
                        data={"List-Unsubscribe": "One-Click"},
                        headers=headers,
                        timeout=10
                    )
                    if resp.status_code in (200, 202, 204, 301, 302):
                        return True, f"HTTP POST 1-Click unsubscribe succeeded ({resp.status_code})"
                # Fallback to GET
                resp = requests.get(http_url, headers=headers, timeout=10)
                if resp.status_code in (200, 202, 204, 301, 302):
                    return True, f"HTTP GET unsubscribe sent ({resp.status_code})"
                return False, f"HTTP response returned code {resp.status_code}"
            except Exception as e:
                return False, f"HTTP error: {str(e)}"

        if mailto_url:
            try:
                clean_mailto = mailto_url.replace("mailto:", "").strip()
                # Parse address and subject if any e.g. mailto:unsub@domain.com?subject=unsubscribe
                parts = clean_mailto.split("?", 1)
                dest = parts[0]
                sub = "unsubscribe"
                if len(parts) > 1 and "subject=" in parts[1].lower():
                    m = re.search(r"subject=([^&]+)", parts[1], re.IGNORECASE)
                    if m:
                        sub = requests.utils.unquote(m.group(1))
                
                self.send_email(
                    to_addr=dest,
                    subject=sub,
                    html_content="<p>Please unsubscribe this address from your mailing list.</p>",
                    text_content="Please unsubscribe this address from your mailing list."
                )
                return True, f"Sent automated RFC 2369 unsubscribe email to {dest}"
            except Exception as e:
                return False, f"Mailto error: {str(e)}"

        return False, "No unsubscribe URL or mailto found"

    def close(self):
        if self.imap is not None:
            try:
                self.imap.logout()
            except Exception:
                pass
            self.imap = None
