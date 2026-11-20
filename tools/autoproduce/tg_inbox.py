"""صندوق استقبال خاص عبر بوت تيليجرام (طلب المالك 20 نوفمبر 2026).
المالك وحده يرسل للبوت مقطعاً (فيديو أو ملفاً) أو رابطاً يملك حق استعماله، فيُسجَّل وصفه في inbox.json (بلا الوسائط نفسها)،
ويستعمل خط الإنتاج المقطع بمصدر `tg://<file_id>` أو الرابط بـ yt-dlp. رسائل غير المالك تُتجاهل كلياً.
حد واجهة بوتات تيليجرام لتنزيل الملفات 20 ميغابايت؛ الأكبر يُرسل رابطاً بدلاً منه.
المتغيرات: TELEGRAM_BOT_TOKEN و TELEGRAM_OWNER_ID."""
import json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path

INBOX = Path(__file__).resolve().parent / "inbox.json"
LIMIT = 20 * 1024 * 1024
URL_RE = re.compile(r"https?://[^\s]+")


def api(token, method, **params):
    data = urllib.parse.urlencode(params).encode() if params else None
    with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data), timeout=40) as r:
        return json.load(r)


def parse_update(u, next_id):
    """رسالة المالك ← بند صندوق، أو None إن لم تحوِ وسائط أو رابطاً."""
    m = u.get("message") or {}
    text = (m.get("caption") or m.get("text") or "").strip()
    urls = URL_RE.findall(text)
    media = m.get("video") or m.get("animation") or (m.get("document") if str(m.get("document", {}).get("mime_type", "")).startswith("video/") else None)
    if not media and not urls:
        return None
    item = {"id": next_id, "update_id": u["update_id"], "date": m.get("date"), "caption": text, "urls": urls}
    if media:
        item.update({"kind": "file", "file_id": media["file_id"], "file_unique_id": media.get("file_unique_id"),
                     "name": media.get("file_name", ""), "size": media.get("file_size", 0),
                     "width": media.get("width", 0), "height": media.get("height", 0), "duration": media.get("duration", 0)})
    else:
        item["kind"] = "link"
    return item


def reply_text(item):
    if item["kind"] == "link":
        return f"استلمت #{item['id']}: رابط ({len(item['urls'])}). ستُحمَّل اللقطات من خادم الإنتاج حين أستعملها."
    s = f"استلمت #{item['id']}: فيديو {item['width']}x{item['height']}، {item['duration']} ثانية، {item['size'] // 1024} كيلوبايت."
    if item["size"] > LIMIT:
        s += " تنبيه: أكبر من 20 ميغابايت، لا يستطيع البوت تنزيله؛ أرسل رابطاً أو نسخة مضغوطة."
    elif item["height"] and min(item["width"], item["height"]) < 720:
        s += " تنبيه: الجودة أقل من 720، ممنوعة؛ أرسل نسخة 1080 أو أعلى."
    return s


def main():
    token, owner = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_OWNER_ID", "").strip()
    if not token or not owner:
        print("لا أسرار البوت بعد؛ لا شيء يُفعل"); return
    box = json.loads(INBOX.read_text(encoding="utf-8")) if INBOX.exists() else {"last_update_id": 0, "items": []}
    res = api(token, "getUpdates", offset=box["last_update_id"] + 1, timeout=0)
    new = 0
    for u in res.get("result", []):
        box["last_update_id"] = max(box["last_update_id"], u["update_id"])
        m = u.get("message") or {}
        if str((m.get("from") or {}).get("id")) != owner:
            continue  # غير المالك: تجاهل صامت
        item = parse_update(u, len(box["items"]) + 1)
        if item:
            box["items"].append(item); new += 1
            try:
                api(token, "sendMessage", chat_id=owner, text=reply_text(item))
            except Exception:
                pass
    INBOX.write_text(json.dumps(box, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"تحديثات: {len(res.get('result', []))}، جديد للمالك: {new}")


if __name__ == "__main__":
    main()
