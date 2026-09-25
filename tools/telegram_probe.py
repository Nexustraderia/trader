import json
import os
import urllib.request


token = os.environ["TELEGRAM_BOT_TOKEN"]
def api(method: str) -> dict:
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", timeout=20) as response:
        return json.load(response)


identity = api("getMe")
webhook = api("getWebhookInfo")
payload = api("getUpdates?limit=100")
print(json.dumps({
    "bot": identity.get("result", {}).get("username"),
    "webhook_url_configured": bool(webhook.get("result", {}).get("url")),
    "pending_update_count": webhook.get("result", {}).get("pending_update_count"),
}, ensure_ascii=False))
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
    origin = message.get("forward_origin", {})
    origin_chat = origin.get("chat", {}) if origin.get("type") == "channel" else message.get("forward_from_chat", {})
    if origin_chat.get("id") is not None:
        seen[str(origin_chat["id"])] = origin_chat.get("title") or origin_chat.get("username") or "forwarded_channel"
print(json.dumps({"chats": seen}, ensure_ascii=False))
