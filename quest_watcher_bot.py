"""
Quest Watcher Bot — interactive version
----------------------------------------
A real Telegram bot you control by chatting with it. No file editing
needed after setup.

Commands (send these to your bot in Telegram):
  /start              - register yourself so the bot knows who to notify
  /add <subdomain>     - start watching a Zealy community
                          e.g. /add example-community
  /remove <subdomain>  - stop watching a community
  /list                - show what's currently being watched

It only watches and notifies you. You still open each quest and
complete it yourself, on your one real account.

SETUP
-----
1. Create a bot via @BotFather on Telegram, get your API token.
2. Paste the token into BOT_TOKEN below.
3. Install dependency:
     pip install requests --break-system-packages
4. Run it:
     python3 quest_watcher_bot.py
5. In Telegram, open a chat with your bot and send /start, then
   /add <subdomain> for each community you want watched.

Runs fine on Termux (Android). Disable battery optimization for
Termux and keep it running in the foreground/acquire wakelock
(termux-wake-lock) so Android doesn't kill it in the background.
"""

import requests
import time
import json
import os
import threading

# ── CONFIG ────────────────────────────────────────────────
# On Railway, set BOT_TOKEN as an environment variable instead of
# pasting it here — keeps your token out of your GitHub repo.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE")

POLL_QUEST_INTERVAL = 60     # seconds between quest board checks
POLL_TELEGRAM_INTERVAL = 2   # seconds between checking for new commands
STATE_FILE = "watcher_state.json"
# ──────────────────────────────────────────────────────────

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
state_lock = threading.Lock()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"chat_id": None, "communities": [], "seen": {}, "update_offset": 0}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_message(chat_id, text):
    try:
        requests.post(
            f"{API_BASE}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"Telegram send failed: {e}")


def fetch_quests(subdomain):
    url = f"https://api-v2.zealy.io/public/communities/{subdomain}/quests"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"Failed to fetch {subdomain}: {e}")
        return None  # None = fetch failed, [] = valid empty list


def quest_watch_loop():
    while True:
        with state_lock:
            state = load_state()
            chat_id = state.get("chat_id")
            communities = list(state.get("communities", []))
            seen = state.get("seen", {})

        if chat_id:
            for subdomain in communities:
                quests = fetch_quests(subdomain)
                if quests is None:
                    continue  # skip this round, don't wipe seen data
                seen_ids = set(seen.get(subdomain, []))
                for quest in quests:
                    qid = quest.get("id")
                    name = quest.get("name", "Unnamed quest")
                    if qid and qid not in seen_ids:
                        send_message(
                            chat_id,
                            f"🆕 New quest on {subdomain}:\n{name}\n"
                            f"https://zealy.io/cw/{subdomain}/questboard",
                        )
                        seen_ids.add(qid)
                seen[subdomain] = list(seen_ids)

            with state_lock:
                state = load_state()
                state["seen"] = seen
                save_state(state)

        time.sleep(POLL_QUEST_INTERVAL)


def handle_command(chat_id, text):
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    with state_lock:
        state = load_state()

        if cmd == "/start":
            state["chat_id"] = chat_id
            save_state(state)
            send_message(
                chat_id,
                "Registered! Use /add <subdomain> to start watching a "
                "Zealy community, /list to see what's watched, "
                "/remove <subdomain> to stop watching one.",
            )

        elif cmd == "/add":
            if not arg:
                send_message(chat_id, "Usage: /add <subdomain>")
            elif arg in state["communities"]:
                send_message(chat_id, f"Already watching '{arg}'.")
            else:
                state["communities"].append(arg)
                save_state(state)
                send_message(chat_id, f"✅ Now watching '{arg}'.")

        elif cmd == "/remove":
            if arg in state["communities"]:
                state["communities"].remove(arg)
                state["seen"].pop(arg, None)
                save_state(state)
                send_message(chat_id, f"🗑 Stopped watching '{arg}'.")
            else:
                send_message(chat_id, f"Not currently watching '{arg}'.")

        elif cmd == "/list":
            communities = state.get("communities", [])
            if communities:
                send_message(chat_id, "Watching:\n" + "\n".join(communities))
            else:
                send_message(chat_id, "Not watching anything yet. Use /add <subdomain>.")

        else:
            send_message(chat_id, "Commands: /start, /add <subdomain>, /remove <subdomain>, /list")


def telegram_command_loop():
    while True:
        with state_lock:
            state = load_state()
            offset = state.get("update_offset", 0)

        try:
            r = requests.get(
                f"{API_BASE}/getUpdates",
                params={"offset": offset, "timeout": 10},
                timeout=15,
            )
            r.raise_for_status()
            updates = r.json().get("result", [])
        except requests.RequestException as e:
            print(f"Failed to get updates: {e}")
            time.sleep(POLL_TELEGRAM_INTERVAL)
            continue

        for update in updates:
            update_id = update["update_id"]
            message = update.get("message", {})
            text = message.get("text", "")
            chat_id = message.get("chat", {}).get("id")

            if text and chat_id:
                handle_command(chat_id, text)

            with state_lock:
                state = load_state()
                state["update_offset"] = update_id + 1
                save_state(state)

        time.sleep(POLL_TELEGRAM_INTERVAL)


def main():
    print("Quest watcher bot starting...")
    print("Send /start to your bot in Telegram to register.")

    t1 = threading.Thread(target=quest_watch_loop, daemon=True)
    t2 = threading.Thread(target=telegram_command_loop, daemon=True)
    t1.start()
    t2.start()

    # keep main thread alive
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
