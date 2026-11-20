"""إلغاء المنشورات المجدولة في Buffer (يوتيوب وإنستقرام وفيسبوك) بطلب المالك.
--mode list يعرضها فقط، و--mode delete يحذف المجدول منها (status=scheduled) ثم يتحقق."""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import schedule_buffer as sb

NAMES = {v: k for k, v in sb.CHANNELS.items()}


def scheduled():
    items = sb.cli("posts", "list", "--organization-id", sb.ORG, "--limit", "100",
                   "--fields", "items.id,items.status,items.channelId,items.dueAt,items.text,items.assets.source")["items"]
    return [p for p in items if p["status"] == "scheduled" and p["channelId"] in NAMES]


def show(rows):
    for p in sorted(rows, key=lambda p: p["dueAt"]):
        src = ",".join(a.get("source", "")[:60] for a in (p.get("assets") or []))
        print(p["dueAt"], NAMES[p["channelId"]], p["id"], (p.get("text") or "").split("\n")[0][:50], "| media:", src)
    print("المجموع:", len(rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["list", "delete"], default="list")
    ap.add_argument("--ids", default="", help="معرّفات محددة مفصولة بفواصل (فارغ = كل المجدول)")
    a = ap.parse_args()
    rows = scheduled()
    ids = [i.strip() for i in a.ids.split(",") if i.strip()]
    if ids:
        rows = [p for p in rows if p["id"] in ids]
    show(rows)
    if a.mode == "delete":
        for p in rows:
            sb.cli("posts", "delete", "--id", p["id"])
            print("حُذف:", NAMES[p["channelId"]], p["dueAt"], p["id"], flush=True)
        left = [p for p in scheduled() if not ids or p["id"] in ids]
        print("المتبقي بعد الحذف:", len(left))
        if left:
            sys.exit(1)
