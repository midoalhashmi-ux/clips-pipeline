"""يجلب من صفحة Rotten Tomatoes لعمل ما: معرّف التريلر الرسمي والملخص، ويطبع رابط الجلب الجاهز لـqueue.json.
مثال: python tools/autoproduce/rt_find.py m/chainsaw_man_the_movie_reze_arc   (للمسلسلات: tv/<slug>)"""
import html, re, sys, urllib.request

slug = sys.argv[1].strip("/")
req = urllib.request.Request(f"https://www.rottentomatoes.com/{slug}", headers={"User-Agent": "Mozilla/5.0"})
h = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
title = re.findall(r"<title>([^<]+)</title>", h)
print("العنوان:", html.unescape(title[0]) if title else "?")
ids = []
for m in re.finditer(r'publicId":"([^"]+)"', h):
    ctx = h[max(0, m.start() - 300):m.end() + 300]
    names = re.findall(r'"(?:title|name)":"([^"]{3,100})"', ctx)
    if m.group(1) and m.group(1) not in [i for i, _ in ids]:
        ids.append((m.group(1), names[-1] if names else ""))
for i, n in ids:
    print(f"تريلر: {i} | {n}\n  source_url: https://link.theplatform.com/s/NGweTC/media/{i}?formats=MPEG4")
if not ids:
    print("لا تريلر ظاهر في الصفحة")
k = h.find("rt-text")
syn = re.findall(r'<rt-text[^>]*data-qa="synopsis-value"[^>]*>([^<]+)<', h) or re.findall(r'([^<>]{120,900})\s*</rt-text>\s*<rt-link aria-label="expand content"', h)
print("الملخص:", html.unescape(syn[0]).strip() if syn else "غير ظاهر")
