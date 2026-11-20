"""بحث كلمات مجاني آلي: اقتراحات يوتيوب وجوجل التلقائية بالعربية لكل عمل (بلا مفتاح).
يكتب keyword-research.json لتعتمد عليه مراجعة SEO عند كتابة النصوص."""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def suggest(q, yt):
    url = "https://suggestqueries.google.com/complete/search?" + urllib.parse.urlencode(
        {"client": "firefox", "hl": "ar", "gl": "SA", **({"ds": "yt"} if yt else {}), "q": q})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))[1]


def main():
    q = [i for i in json.loads((ROOT / "queue.json").read_text(encoding="utf-8")) if i.get("enabled")]
    out = {}
    for it in q:
        ar, en = it["display_title"], it.get("english_title", "")
        seeds = [ar, en, f"{it['type'] == 'anime' and 'أنمي' or 'مسلسل'} {ar}", f"{ar} ترشيح", f"قصة {ar}", f"{en} ترجمة"]
        found = {}
        for s in [x for x in seeds if x]:
            for yt in (True, False):
                try:
                    for g in suggest(s, yt):
                        found.setdefault(g, {"seed": s, "youtube": yt})
                except Exception as e:  # الشبكة قد تحجب؛ لا يوقف الإنتاج
                    print("تعذّر:", s, e, file=sys.stderr)
                time.sleep(0.4)
        out[it["key"]] = {"seeds": seeds, "suggestions": [dict(text=k, **v) for k, v in found.items()]}
        print(it["key"], len(found), "اقتراحاً")
        for g in list(found)[:14]:
            print("   -", g)
    (ROOT / "keyword-research.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
