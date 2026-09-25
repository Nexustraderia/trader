import json
import os
import urllib.request


token = os.environ["TELEGRAM_BOT_TOKEN"]
url = f"https://api.telegram.org/bot{token}/getUpdates?limit=100"
with urllib.request.urlopen(url, timeout=20) as response:
    payload = json.load(response)
if not payload.get("ok"):
    raise SystemExit("Telegram API returned an error")
seen = {}
for update in payload.get("result", []):
    message = update.get("channel_post") or update.get("message") or update.get("edited_channel_post")
    if not message:
        continue
    chat = message.get("chat", {})
    if chat.get("id") is not None:
        seen[str(chat["id"])] = chat.get("title") or chat.get("username") or chat.get("type", "unknown")
print(json.dumps({"chats": seen}, ensure_ascii=False))
