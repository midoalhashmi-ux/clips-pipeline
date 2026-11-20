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
        # طلب المالك 20 نوفمبر 2026: اللقطات تناسب القصة (إيمو ونيكا يظهران حين يُذكران، لا مشاهد عادية)
        if not it.get("footage_checked") or len(str(it.get("footage_match", ""))) < 20:
            errs.append("اللقطات لم تُراجَع: املأ footage_match (ما يظهر ومطابقته للسرد) وضع footage_checked=true بعد مراجعة شريط المصغّرات")
        for sg in it.get("segments", []):
            if not str(sg.get("shows", "")).strip():
                errs.append("كل مقطع في segments يحتاج وصف shows لما يظهر فيه")
        # طلب المالك 20 نوفمبر 2026: اللقطات غير الرسمية خفيفة وقليلة (official=false)
        segs = it.get("segments", [])
        unofficial = [float(sg.get("dur", 0)) for sg in segs if sg.get("official", True) is False]
        if unofficial:
            total = sum(float(sg.get("dur", 0)) for sg in segs) or 1.0
            if max(unofficial) > 3.5:
                errs.append("لقطة غير رسمية أطول من 3.5 ثانية")
            if sum(unofficial) > 9 or sum(unofficial) / total > 0.3:
                errs.append("اللقطات غير الرسمية تتجاوز 9 ثوانٍ أو 30% من المقطع")
            if not str(it.get("source_credit", "")).strip():
                errs.append("لقطات غير رسمية بلا source_credit (رابط المقطع وناشره)")
        # طلب المالك 20 نوفمبر 2026: لحظات صوت الأنمي قصيرة وقليلة ورسمية، وبين الجمل لا بعد السؤال الأخير
        beats = it.get("beats") or []
        if beats:
            n = len([p for p in re.split(r"(?<=[.؟!?])\s+", it.get("speech", "").strip()) if p])
            durs = [float(b.get("dur", 0)) for b in beats]
            if len(beats) > 2 or max(durs) > 3 or sum(durs) > 5:
                errs.append("لحظات الأنمي: لحظتان كحد أقصى، كل واحدة 3 ثوانٍ، ومجموعها 5 ثوانٍ")
            for b in beats:
                if b.get("official") is not True:
                    errs.append("لحظة أنمي من مصدر غير رسمي (official=true مطلوب)")
                if not str(b.get("shows", "")).strip() or not str(b.get("hears", "")).strip():
                    errs.append("كل لحظة أنمي تحتاج shows (ما يظهر) وhears (ما يُسمع)")
                if not 1 <= int(b.get("after", 0)) <= n - 1:
                    errs.append(f"لحظة الأنمي after خارج الجمل (1 إلى {n - 1})")
            if it.get("speech_end"):
                errs.append("لحظات الأنمي لمقاطع الشرح بلا speech_end")
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
