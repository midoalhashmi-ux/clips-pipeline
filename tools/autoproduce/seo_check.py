"""فحص SEO آلي لقائمة الانتظار قبل الإنتاج، وفق docs/marketing/seo-publishing-checklist.md.
--rehash يعيد حساب بصمات النصوص بعد مراجعة بشرية؛ بدونه يفشل الفحص إن تغيّر نص دون مراجعة."""
import hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "queue.json"
LINK, TG = "https://binsheikh.pages.dev", "@BinSheikh_app"
# تيك توك (قرار المالك 18 نوفمبر 2026): كلمة «تحميل» في رسالة خاصة ويصل الرابط تلقائياً
TIKTOK_CTA = "للتحميل على أندرويد: أرسل كلمة «تحميل» في رسالة خاصة لحسابنا هنا على تيك توك، وسيصلك الرابط تلقائياً."
TAGS = {"youtube": 3, "instagram": 3, "tiktok": 3, "facebook": 2}


SOURCE_WORDS = re.compile(r"الفصل|المانغا|المانجا|الحلقة|المجلد")  # طلب المالك 20 نوفمبر 2026: لا ذكر لمصدر المعلومة في الصوت


def check(it):
    errs, seo = [], it.get("seo")
    if not seo:
        return [f"{it['key']}: لا يوجد حقل seo"]
    title, texts, rev = seo["youtube_title"], seo["texts"], seo["seo_review"]
    if it.get("format") == "explainer":
        for fld in ("speech", "speech_end"):
            if SOURCE_WORDS.search(it.get(fld, "")):
                errs.append(f"{fld} يذكر مصدر المعلومة (فصل أو حلقة أو مجلد أو مانغا)؛ تُروى حقيقة مباشرة")
    if len(title) > 70:
        errs.append(f"العنوان أطول من 70 حرفاً ({len(title)})")
    if not (re.search(r"[؀-ۿ]", title) and re.search(r"[A-Za-z]", title)):
        errs.append("العنوان يجب أن يحوي الاسم العربي والإنجليزي")
    kw = rev["primary_keyword"]
    if not all(w in title for w in kw.split()[-1:]):
        errs.append("عبارة البحث الرئيسية غير ظاهرة في العنوان")
    for plat, n in TAGS.items():
        t = texts.get(plat, "")
        if not t:
            errs.append(f"نص {plat} مفقود"); continue
        if len(re.findall(r"(?<!\w)#\w+", t)) != n:
            errs.append(f"عدد وسوم {plat} يجب أن يكون {n}")
        if plat == "tiktok":
            if TIKTOK_CTA not in t:
                errs.append("تيك توك: عبارة «أرسل كلمة تحميل» مفقودة")
        elif LINK not in t:
            errs.append(f"{plat}: رابط التحميل مفقود")
        if kw.split()[0] not in t.split("\n")[0] and kw.split()[0] not in t[:200]:
            errs.append(f"{plat}: عبارة البحث لا تظهر في بداية النص")
    got = rev.get("reviewed_text_sha256", {})
    for plat, t in texts.items():
        if got.get(plat) != hashlib.sha256(t.encode()).hexdigest():
            errs.append(f"{plat}: النص تغيّر بعد المراجعة؛ راجعه ثم شغّل --rehash")
    return [f"{it['key']}: {e}" for e in errs]


if __name__ == "__main__":
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    if "--rehash" in sys.argv:
        for it in q:
            if "seo" in it:
                it["seo"]["seo_review"]["reviewed_text_sha256"] = {p: hashlib.sha256(t.encode()).hexdigest() for p, t in it["seo"]["texts"].items()}
        QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("أُعيد حساب البصمات")
    bad = [e for it in q if it.get("enabled") for e in check(it)]
    for e in bad:
        print("خطأ SEO:", e)
    if bad:
        sys.exit(1)
    print("فحص SEO سليم لكل الأعمال المفعّلة")
