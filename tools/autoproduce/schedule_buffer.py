"""يجهّز مقاطع الدفعة للاستضافة المؤقتة ويجدول يوتيوب وإنستقرام وفيسبوك عبر Buffer.
تيك توك لا يُجدول هنا؛ يطبع روابطه ليجدولها Claude عبر Metricool."""
import argparse, hashlib, json, os, shutil, subprocess, sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
ORG = "6ace6fddf3bf9d17855f118e"
CHANNELS = {"youtube": "6aceb355778b240e2fff0d09", "instagram": "6ad214cf778b240e2f2887b7", "facebook": "6ad491ce778b240e2f46d980"}
PLATFORMS = list(CHANNELS) + ["tiktok"]
TZ = ZoneInfo("Asia/Riyadh")
FIELDS = "id,status,channelId,dueAt,text,assets.source,metadata.title,schedulingType,shareMode"


def utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def occupied():
    """أيام فيها منشورات مجدولة فعلاً على قنوات Buffer، حتى لا نتصادم معها."""
    if not os.environ.get("BUFFER_API_KEY"):
        return set()
    try:
        items = cli("posts", "list", "--organization-id", ORG, "--limit", "100",
            "--fields", "items.id,items.status,items.channelId,items.dueAt")["items"]
    except Exception as e:
        print("تعذّرت قراءة الحجوزات:", str(e)[:200]); return set()
    return {datetime.fromisoformat(p["dueAt"].replace("Z", "+00:00")).astimezone(TZ).date()
            for p in items if p["status"] == "scheduled" and p["channelId"] in CHANNELS.values()}


def prepare(clips, site, base_url, post_hour):
    queue = [i for i in json.loads((ROOT / "queue.json").read_text(encoding="utf-8")) if i.get("enabled")]
    now = datetime.now(TZ)
    day = now.date() if now.time() < time(post_hour - 1, 30) else now.date() + timedelta(days=1)
    rows = []
    busy = occupied()
    for it in sorted(queue, key=lambda i: i["date"]):
        d = next(iter(Path(clips).glob(f"*-{it['key']}")), None)  # بالمفتاح: قد يتغيّر التاريخ بعد الإنتاج
        if not d:
            continue
        day = max(day, date.fromisoformat(it["date"]))  # لا قبل الموعد المخطط بقائمة الانتظار
        while day in busy:
            day += timedelta(days=1)
        due = datetime.combine(day, time(post_hour, 0), TZ)
        for plat in PLATFORMS:
            src = d / f"video-{plat}.mp4"
            if not src.exists():
                continue
            h = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
            rel = f"{day.isoformat()}/{it['key']}-{plat}-{h}.mp4"
            (site / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, site / rel)
            seo = it.get("seo", {})
            text = seo.get("texts", {}).get(plat) or (it["description"] if plat == "youtube" else it["short_caption"])
            rows.append(dict(key=it["key"], platform=plat, date=day.isoformat(), due_at_utc=utc(due),
                title=seo.get("youtube_title") or it["title"], text=text, url=f"{base_url}/{rel}"))
        day += timedelta(days=1)
    if not rows:
        sys.exit("لا مقاطع مطابقة لقائمة الانتظار داخل مجلد المقاطع")
    expires = max(datetime.fromisoformat(r["due_at_utc"].replace("Z", "+00:00")) for r in rows) + timedelta(hours=36)
    (site / "expires.txt").write_text(expires.isoformat(), encoding="utf-8")
    (site / "index.html").write_text("<!doctype html><title>media</title>", encoding="utf-8")
    return rows


def cli(*args, request=None):
    cmd = ["npx", "--yes", "@bufferapp/cli", *args, "--quiet", "--output", "json"] + (["--input", "-"] if request is not None else [])
    p = subprocess.run(cmd, capture_output=True, text=True, input=json.dumps(request, ensure_ascii=False) if request is not None else None)
    if p.returncode:
        raise RuntimeError((p.stderr + p.stdout)[:1400])
    return json.loads(p.stdout)


def schedule(rows):
    listing = cli("posts", "list", "--organization-id", ORG, "--limit", "100",
        "--fields", "items.id,items.status,items.channelId,items.dueAt,pageInfo.hasNextPage")["items"]
    for r in [r for r in rows if r["platform"] in CHANNELS]:
        ch = CHANNELS[r["platform"]]
        if any(p.get("channelId") == ch and p.get("dueAt") == r["due_at_utc"] and p["status"] in ("scheduled", "pending", "sending", "sent") for p in listing):
            print("موجود مسبقاً:", r["platform"], r["key"]); r["status"] = "exists"; continue
        meta = {"youtube": dict(title=r["title"], categoryId="24", privacy="public", madeForKids=False, isAiGenerated=True),
                "instagram": dict(type="reel", shouldShareToFeed=True, isAiGenerated=True),
                "facebook": dict(type="reel")}[r["platform"]]
        video = {"url": r["url"]}
        if r["platform"] == "instagram":
            video["metadata"] = {"thumbnailOffset": 1000}
        req = dict(channelId=ch, mode="customScheduled", schedulingType="automatic", dueAt=r["due_at_utc"], text=r["text"],
            metadata={r["platform"]: meta}, aiAssisted=True, assets=[{"video": video}])
        f = ROOT / "_buffer_req.json"; f.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
        res = cli("posts", "create", "--input", str(f), "--fields", "post.id,post.status"); f.unlink()
        pid = res.get("post", {}).get("id")
        assert pid, res
        post = cli("posts", "get", "--id", pid, "--fields", FIELDS)
        assert post["status"] == "scheduled" and post["dueAt"] == r["due_at_utc"], post
        r["status"], r["post_id"] = "scheduled", pid
        print("جُدول:", r["platform"], r["key"], r["due_at_utc"], pid, flush=True)


FULL = "id,status,channelId,dueAt,assets,text,metadata,schedulingType,shareMode,allowedActions"


def edit_scheduled(rows):
    """يعدّل النص (وعنوان يوتيوب) للمنشورات المجدولة فقط، دون لمس الفيديو أو الموعد، مع قراءة تحقق."""
    listing = cli("posts", "list", "--organization-id", ORG, "--limit", "100",
        "--fields", "items.id,items.status,items.channelId,items.dueAt")["items"]
    for r in [r for r in rows if r["platform"] in CHANNELS]:
        ch = CHANNELS[r["platform"]]
        m = [p for p in listing if p["channelId"] == ch and p["dueAt"] == r["due_at_utc"] and p["status"] == "scheduled"]
        if len(m) != 1:
            print("تخطّي (غير مجدول أو غير فريد):", r["platform"], r["key"], len(m)); continue
        cur = cli("posts", "get", "--id", m[0]["id"], "--fields", FULL)
        if "updatePost" not in cur.get("allowedActions", []):
            print("تخطّي (لا يقبل التعديل):", r["platform"], r["key"]); continue
        assets = [{"video": {"url": a["source"], **({"metadata": {"thumbnailOffset": a["video"]["thumbnailOffset"]}}
                  if a.get("video", {}).get("thumbnailOffset") is not None else {})}} for a in cur["assets"]]
        md = cur["metadata"]
        if r["platform"] == "youtube":
            pm = {k: md[k] for k in ("embeddable", "isAiGenerated", "license", "madeForKids", "notifySubscribers", "privacy") if k in md}
            pm.update(title=r["title"], categoryId=md["category"]["categoryId"])
        elif r["platform"] == "instagram":
            pm = {k: md[k] for k in ("isAiGenerated", "shouldShareToFeed", "type") if k in md}
        else:
            pm = {"type": md["type"]}
        req = {"id": cur["id"], "text": r["text"], "metadata": {r["platform"]: pm}, "assets": assets}
        reply = cli("posts", "edit", "--fields", "post.id,post.status,post.text,post.metadata", request=req)
        assert reply.get("post", {}).get("id") == cur["id"], reply
        new = cli("posts", "get", "--id", cur["id"], "--fields", FULL)
        assert new["text"] == r["text"] and new["status"] == "scheduled" and new["dueAt"] == cur["dueAt"], new
        assert new["assets"] == cur["assets"], "تغيّر الفيديو!"
        if r["platform"] == "youtube":
            assert new["metadata"]["title"] == r["title"]
        print("عُدِّل وتحقق:", r["platform"], r["key"], cur["id"], flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True); ap.add_argument("--site", required=True)
    ap.add_argument("--base-url", required=True); ap.add_argument("--hour", type=int, default=20)
    ap.add_argument("--plan-out", required=True); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rows = prepare(a.clips, Path(a.site), a.base_url.rstrip("/"), a.hour)
    Path(a.plan_out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if not a.dry_run:
        schedule(rows); Path(a.plan_out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in rows:
        if r["platform"] == "tiktok":
            print("TIKTOK|" + "|".join([r["date"], r["due_at_utc"], r["key"], r["url"]]))
