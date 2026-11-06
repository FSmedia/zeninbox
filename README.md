# ZenInbox: Intelligent Email Gatekeeper, Daily Digest & Subscription Cleaner

**ZenInbox** is a private, lightning-fast Gmail management platform running locally on your computer. It combines intelligent inbound sender screening, daily digest bundling, open-rate analytics, automated subscription cleaning, and an **AI Inbox Advisor** into a single cohesive interface.

---

## Key Features

### 1. AI Inbox Advisor & 1-Click Automated Actions
* Scans all incoming senders, read frequencies, subjects, and headers.
* Classifies senders into actionable categories:
  * **VIP / Critical Financial** (Banks like GTCO/Access, Selar, Ileoja, receipts, invoices) &rarr; Auto-star & direct inbox delivery.
  * **Inactive / Stale Newsletters** (&lt; 10% opens) &rarr; 1-Click Unsubscribe & Purge All.
  * **Backlogged Frequent Newsletters** &rarr; **Keep Newest Edition Only** (preserves the single freshest copy while cleaning out the backlogged duplicates to Trash).
  * **Daily Digest Candidates** &rarr; Bundles recurring subscriptions into a calm digest feed.
* **1-Click "Apply All High-Confidence Actions"**: Purifies your entire inbox in one click, or review and apply recommendations individually.

### 2. "Keep Newest Edition Only" (Fresh Inbox)
* For recurring newsletters (e.g. daily tech digests, newsletters, updates), you often only need the *latest* edition.
* Moves all older backlogged issues from that sender to Trash while leaving the single newest issue in your inbox.
* **"Prune All to Newest Only"** button lets you clean all backlogged subscriptions simultaneously.

### 3. Rapid Triage Mode (Flash Review)
* Fast, focused card deck interface to triage your subscriptions in seconds.
* Full keyboard shortcuts:
  * `1`: Keep in Inbox
  * `2`: Keep Newest Edition Only
  * `3`: Move to Daily Digest
  * `4`: Unsubscribe & Purge to Trash

### 4. Screening Room (Inbound Gatekeeper)
* Screens unknown, cold, or unsolicited senders before they reach your primary inbox.
* Quarantines them in the Screening Room until approved.
* 1-Click **Allow to Inbox** (adds to VIP allowlist), **Send Challenge** (prompts sender to verify humanity), or **Block & Trash**.

### 5. Daily Digest Feed & Email Dispatch
* Bundles selected newsletters into a calm, magazine-style feed.
* On-demand **"Email Me This Digest Now"** sends a single clean HTML recap to your Gmail inbox.

---

## Running ZenInbox

The application runs locally on your machine at:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

To run or restart at any time:
```powershell
cd C:\Users\FERANMI\.gemini\antigravity\scratch\zeninbox
python run.py
```
