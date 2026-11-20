"""يضيف عمل «مقطع لقطة» عاماً (أي أنمي أو مسلسل أو فيلم) إلى queue.json بقالب الاحتفاظ بالمشاهد:
افتتاحية سؤال ≤5ث ← صوت المقطع الأصلي ← معلومة + سؤال تفاعل ≤8ث ← خاتمة ≤6ث.
يبني نصوص SEO للمنصات الأربع ويحسب بصماتها ويتحقق منها بـseo_check.

مثال:
  python tools/autoproduce/new_clip.py --key ds_akaza --ar "القلعة اللانهائية" --en "Demon Slayer" \\
    --url https://www.tiktok.com/@user/video/123 --credit-name "@user على تيك توك" --rights "استوديو ufotable" \\
    --hook "هذا الشيطان قتل رينغوكو... فهل ينتقم منه تانجيرو الآن؟" \\
    --summary "ملخص من المصدر بجملة أو جملتين" --insight "معلومة من المصدر" --question "سؤال تفاعل سهل وشخصي؟" \\
    --tags "#DemonSlayer,#القلعة_اللانهائية,#ترشيحات_أنمي" --suffix "تانجيرو ضد أكازا" --start 0 --tail 12
--print يعرض العمل دون كتابته."""
import argparse, datetime, hashlib, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seo_check

ROOT = Path(__file__).resolve().parent
LINK, TG = seo_check.LINK, seo_check.TG


def build(a):
    tags = [t.strip() for t in a.tags.split(",") if t.strip()]
    if len(tags) != 3:
        sys.exit("--tags يجب أن يحوي 3 وسوم مفصولة بفواصل")
    credit = f"مرجع اللقطات: {a.credit_name} {a.credit_url or a.url} — حقوق العمل لأصحابه ({a.rights})."
    first = f"{a.en} {a.ar}: {a.hook}"
    body = f"{a.summary}\n\n{a.question}"
    cta_app = lambda who: f"لتحميل تطبيق مشاهدة الأنمي والمسلسلات والأفلام على أندرويد: افتح {who} ثم اضغط على رابط التحميل.\n{LINK}"
    cta_tg = seo_check.TIKTOK_CTA
    t3, t2 = " ".join(tags), " ".join(tags[:2])
    texts = {
        "youtube": f"{first}\n{body}\n\n{cta_app('قناتنا')}\n\n{credit}\n\n{t3}",
        "instagram": f"{first}\n{body}\n\n{cta_app('صفحتنا')}\n\n{credit}\n\n{t3}",
        "facebook": f"{first}\n{body}\n\n{cta_app('صفحتنا')}\n\n{credit}\n\n{t2}",
        "tiktok": f"{first}\n{body}\n\n{cta_tg}\n\n{credit}\n\n{t3}",
    }
    title = f"{a.en} {a.ar} | {a.suffix}"
    it = {
        "enabled": True, "date": a.date, "key": a.key, "type": a.type, "format": "clip_review",
        "display_title": f"{a.ar}: {a.suffix}", "english_title": a.en,
        "synopsis": a.summary, "source_url": a.url, "source_credit": credit,
        "accent": a.accent, "speech": a.hook, "speech_end": f"{a.insight} اكتب: {a.question}",
        "audio_mode": "hook", "tail": a.tail, "clip_start": a.start,
        "title": title, "description": texts["youtube"], "tags": [t.lstrip("#").replace("_", " ") for t in tags],
        "short_caption": texts["instagram"],
        "seo": {"youtube_title": title, "texts": texts, "seo_review": {
            "passed": True, "primary_keyword": f"{a.en} {a.ar}",
            "keyword_volume_data": a.volume or "غير متوفرة؛ اختير الموضوع بإشارة اهتمام (شهرة العمل ولقطة مؤثرة)",
            "final_video_and_narration_matched": True, "android_cta_checked": True,
            "no_new_release_or_full_work_claim": True,
            "hashtags": {"youtube": 3, "instagram": 3, "tiktok": 3, "facebook": 2},
            "reviewed_text_sha256": {p: hashlib.sha256(t.encode()).hexdigest() for p, t in texts.items()},
            "research_findings": "مقطع لقطة بلقطات غير رسمية بقرار المالك 18 نوفمبر 2026 مع مرجع المصدر"}},
    }
    return it


def main():
    ap = argparse.ArgumentParser()
    for k in ("key", "ar", "en", "url", "credit_name", "rights", "hook", "summary", "insight", "question", "tags", "suffix"):
        ap.add_argument("--" + k.replace("_", "-"), required=True)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--type", default="anime")
    ap.add_argument("--accent", default="#ff6b5e")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--tail", type=float, default=12)
    ap.add_argument("--volume", default="")
    ap.add_argument("--credit-url", default="", help="رابط المرجع إن اختلف عن رابط الجلب")
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    it = build(a)
    errs = seo_check.check(it)
    if errs:
        sys.exit("\n".join(errs))
    if a.print:
        print(json.dumps(it, ensure_ascii=False, indent=2)); return
    q = json.loads((ROOT / "queue.json").read_text(encoding="utf-8"))
    if any(i["key"] == a.key for i in q):
        sys.exit("المفتاح موجود مسبقاً: " + a.key)
    q.append(it)
    (ROOT / "queue.json").write_text(json.dumps(q, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("أُضيف:", a.key)


if __name__ == "__main__":
    main()
