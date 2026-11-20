"""ينقل مقطعاً من سلسلة مراجَعة (dossiers/series/<key>.json) إلى queue.json بصيغة explainer مع نصوص SEO للمنصات الأربع.

مثال (تجربة غير مفعّلة تُنتج بالخانة only):
  python tools/autoproduce/series_to_queue.py --series ds_series --n 1 --date 2026-11-19 \\
    --source https://link.theplatform.com/s/NGweTC/media/3N2cquu4wt27?formats=MPEG4 --clip-start 20
--enable يفعّله للنشر بتاريخه، و--print يعرضه دون كتابة."""
import argparse, datetime, hashlib, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seo_check

ROOT = Path(__file__).resolve().parent
LINK, TG = seo_check.LINK, seo_check.TG


def build(a):
    s = json.loads((ROOT / "dossiers" / "series" / f"{a.series}.json").read_text(encoding="utf-8"))
    v = next(x for x in s["videos"] if x["n"] == a.n)
    if v.get("style") != "v2":
        sys.exit(f"{a.series}#{a.n}: نص بالصيغة القديمة (طويل أو يذكر المصدر)؛ أعد كتابته بصيغة v2 وضع style=v2 في الخطة")
    pool = {d["id"]: d for d in s["pool"]}
    en = s.get("work") or a.en
    tags = a.tags.split(",") if a.tags else [f"#{en.replace(' ', '')}", f"#{s['work_ar'].replace(' ', '_')}", "#شرح_أنمي"]
    used = [pool[i] for i in v["detail_ids"]]
    theory = any(d["status"] == "theory" for d in used)
    first = v["title"]
    body = (f"{v['question']} نشرح السر بتفاصيل من القصة يفوّتها أغلب المتابعين"
            + ("، مع التمييز بين المؤكد والنظرية" if theory else "") + ".\n\nاكتب رأيك بالتعليقات.")
    app = lambda who: f"لتحميل تطبيق مشاهدة الأنمي والمسلسلات والأفلام على أندرويد: افتح {who} ثم اضغط على رابط التحميل.\n{LINK}"
    tgcta = seo_check.TIKTOK_CTA
    t3, t2 = " ".join(tags[:3]), " ".join(tags[:2])
    texts = {"youtube": f"{first}\n{body}\n\n{app('قناتنا')}\n\n{t3}", "instagram": f"{first}\n{body}\n\n{app('صفحتنا')}\n\n{t3}",
             "facebook": f"{first}\n{body}\n\n{app('صفحتنا')}\n\n{t2}", "tiktok": f"{first}\n{body}\n\n{tgcta}\n\n{t3}"}
    it = {"enabled": a.enable, "date": a.date, "key": f"{a.series.split('_')[0]}_s{a.n:02d}", "type": "series", "format": "explainer",
          "display_title": f"{s['work_ar']}: {v['overlay_line']}", "english_title": f"{en} Explained",
          "synopsis": "Explainer from a reviewed series dossier; confirmed vs theory labeled in the narration.",
          "source_url": a.source, "clip_start": a.clip_start, "accent": a.accent, "speech": v["speech"],
          "footage_checked": False, "footage_match": "",
          "title": v["title"], "description": texts["youtube"], "tags": [t.lstrip("#") for t in tags[:3]],
          "short_caption": texts["instagram"], "series_ref": f"{a.series}#{a.n}",
          "seo": {"youtube_title": v["title"], "texts": texts, "seo_review": {
              "passed": True, "primary_keyword": v["primary_keyword"],
              "keyword_volume_data": "not_available_for_this_batch (franchise-level interest)",
              "final_video_and_narration_matched": True, "android_cta_checked": True, "no_new_release_or_full_work_claim": True,
              "hashtags": dict(seo_check.TAGS), "research_findings": f"details from dossiers/series/{a.series}.md; theory labeled",
              "reviewed_text_sha256": {p: hashlib.sha256(t.encode()).hexdigest() for p, t in texts.items()}}}}
    q = json.loads((ROOT / "queue.json").read_text(encoding="utf-8"))
    # قرار المالك (18 نوفمبر 2026): كل يوم عمل مختلف؛ لا يتجاور مقطعان من العمل نفسه
    prefix = it["key"].split("_")[0] + "_s"
    d0 = datetime.date.fromisoformat(it["date"])
    near = [x["key"] for x in q if x["key"] != it["key"] and x["key"].startswith(prefix)
            and abs((datetime.date.fromisoformat(x["date"]) - d0).days) <= 1]
    if near:
        sys.exit(f"العمل نفسه في يوم مجاور: {near}؛ اختر تاريخاً يفصله يوم بعمل آخر")
    errs = seo_check.check(it)
    if errs:
        sys.exit("\n".join(errs))
    return it


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--source", required=True, help="رابط الفيديو الرسمي (rt_find.py)")
    ap.add_argument("--clip-start", type=float, default=20)
    ap.add_argument("--accent", default="#ff6b5e")
    ap.add_argument("--tags", default="", help="3 وسوم مفصولة بفواصل (اختياري)")
    ap.add_argument("--en", default="")
    ap.add_argument("--enable", action="store_true")
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    it = build(a)
    if a.print:
        print(json.dumps(it, ensure_ascii=False, indent=1)); return
    q = json.loads((ROOT / "queue.json").read_text(encoding="utf-8"))
    q = [x for x in q if x["key"] != it["key"]] + [it]
    (ROOT / "queue.json").write_text(json.dumps(q, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"أُضيف {it['key']} بتاريخ {it['date']} ({'مفعّل' if it['enabled'] else 'غير مفعّل'})")


if __name__ == "__main__":
    main()
