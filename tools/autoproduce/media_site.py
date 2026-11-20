"""يعيد بناء الموقع المؤقت للفيديوهات بكل المقاطع المجدولة معاً، لأن Buffer يقرأ الفيديو من الرابط وقت النشر،
وكل نشر على Cloudflare Pages يستبدل الموقع كاملاً. المسار نفسه الذي استعمله schedule_buffer.prepare:
<التاريخ>/<المفتاح>-<المنصة>-<أول 8 من بصمة الملف>.mp4
الاستعمال: python media_site.py --manifest media_manifest.json --clips-root runs --site site
(كل تشغيل إنتاج يُنزَّل في runs/<run_id>/)."""
import argparse, hashlib, json, shutil
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

PLATFORMS = ["youtube", "instagram", "facebook", "tiktok"]

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True); ap.add_argument("--clips-root", required=True); ap.add_argument("--site", required=True)
a = ap.parse_args()
site, root = Path(a.site), Path(a.clips_root)
site.mkdir(parents=True, exist_ok=True)
today = date.today()
n, last = 0, today
for m in json.loads(Path(a.manifest).read_text(encoding="utf-8")):
    d = date.fromisoformat(m["date"])
    if d < today - timedelta(days=1):
        continue  # نُشر وانتهى
    src_dir = next(iter((root / m["run_id"]).glob(f"*-{m['key']}")), None)
    if not src_dir:
        print("مفقود:", m); continue
    for plat in PLATFORMS:
        f = src_dir / f"video-{plat}.mp4"
        if not f.exists():
            continue
        h = hashlib.sha256(f.read_bytes()).hexdigest()[:8]
        dst = site / m["date"] / f"{m['key']}-{plat}-{h}.mp4"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy(f, dst); n += 1
        print("مستضاف:", dst.relative_to(site))
    last = max(last, d)
exp = datetime.combine(last + timedelta(days=2), time(0), timezone.utc)
(site / "expires.txt").write_text(exp.isoformat(), encoding="utf-8")
if not (site / "index.html").exists():
    (site / "index.html").write_text("<!doctype html><title>media</title>", encoding="utf-8")
print("أُضيف", n, "ملفاً")
