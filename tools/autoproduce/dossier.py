"""ملف معلومات لحدث من عمل مشهور: يجمع التفاصيل الخفية الموثّقة ثم يكتب نص مقطع شرح جاهز.

المراحل:
  1. جمع خام مجاني بلا مفتاح: AniList (وصف وشخصيات) + Jikan/MyAnimeList (أرقام واهتمام) + ويكي Fandom (صفحات الحدث والشخصيات).
  2. بحث موسّع: Claude مع بحث الويب وجلب الصفحات يستخرج التفاصيل التي يفوّتها أغلب المتابعين، ولكل تفصيل مصدر.
  3. تدقيق مستقل: استدعاء ثانٍ يعيد فحص كل تفصيل من مصادره ويصنّفه: يُبقى / نظرية / يُحذف.
  4. كتابة النص: بنية مقطع الشرح المعتمدة في Sillks/ahmedia-marketing-video/SKILL.md من أقوى التفاصيل المؤكدة.

الناتج: tools/autoproduce/dossiers/<key>.json (كل المراحل) و<key>.md (تقرير عربي للمراجعة قبل الإنتاج).
لا يُضاف شيء إلى queue.json آلياً: المالك يراجع ثم يُضاف العمل بـnew_clip.py أو يدوياً.

مثال:
  python tools/autoproduce/dossier.py --key ds_akaza_women --work "Demon Slayer" \\
    --event "لماذا لا يقتل أكازا النساء أبداً؟" --terms "Akaza,Hakuji,Koyuki,Keizo"
"""
import argparse, html, json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dossiers"
MODEL = os.environ.get("DOSSIER_MODEL", "claude-opus-5-5")
UA = {"User-Agent": "AhmediaDossier/1.0 (content research script)"}
WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 12},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 10, "max_content_tokens": 20000},
]
# أسماء ويكي Fandom للأعمال المشهورة؛ غير المذكور يُخمَّن من الاسم الإنجليزي أو يُمرَّر بـ--wiki
WIKIS = {
    "demon slayer": "kimetsu-no-yaiba", "one piece": "onepiece", "jujutsu kaisen": "jujutsu-kaisen",
    "attack on titan": "attackontitan", "naruto": "naruto", "boruto": "naruto", "bleach": "bleach",
    "hunter x hunter": "hunterxhunter", "my hero academia": "myheroacademia", "solo leveling": "solo-leveling",
    "black clover": "blackclover", "chainsaw man": "chainsaw-man", "dragon ball": "dragonball",
    "tokyo revengers": "tokyorevengers", "death note": "deathnote", "fullmetal alchemist": "fma",
    "vinland saga": "vinlandsaga", "frieren": "frieren", "spy x family": "spy-x-family",
    "blue lock": "bluelock", "kaiju no. 8": "kaiju-no-8", "dandadan": "dandadan",
    "hell's paradise": "jigokuraku", "sakamoto days": "sakamoto-days", "the apothecary diaries": "kusuriya-no-hitorigoto",
}
NO_PIRACY = ("Never cite or fetch manga scanlation or piracy sites; use official releases, Fandom wikis, "
             "author interviews, official databooks/fanbooks as summarised by wikis, and reputable news.")


# ---------- المرحلة 1: جمع خام مجاني ----------
def http_json(url, data=None, headers=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data, {**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # الشبكة الخارجية غير مضمونة؛ المرحلة الخام اختيارية
            if i == tries - 1:
                print(f"تعذّر الجلب: {url[:90]} — {e}", file=sys.stderr)
                return None
            time.sleep(2 * (i + 1))


def strip_html(s):
    s = re.sub(r"<(script|style|table|aside|figure)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def anilist(work):
    q = """query($s:String){Media(search:$s,type:ANIME,sort:POPULARITY_DESC){id title{romaji english native}
      description(asHtml:false) popularity favourites trending averageScore episodes status
      characters(sort:FAVOURITES_DESC,perPage:12){nodes{name{full native} description(asHtml:false)}}}}"""
    d = http_json("https://graphql.anilist.co", json.dumps({"query": q, "variables": {"s": work}}).encode(),
                  {"Content-Type": "application/json", "Accept": "application/json"})
    m = (d or {}).get("data", {}).get("Media")
    if not m:
        return None
    for c in m["characters"]["nodes"]:  # وصف الشخصيات طويل؛ يكفي أوله
        c["description"] = strip_html(c.get("description") or "")[:900]
    m["description"] = strip_html(m.get("description") or "")
    return m


def jikan(work):
    d = http_json("https://api.jikan.moe/v4/anime?" + urllib.parse.urlencode({"q": work, "limit": 1, "order_by": "members", "sort": "desc"}))
    a = ((d or {}).get("data") or [None])[0]
    if not a:
        return None
    return {k: a.get(k) for k in ("mal_id", "url", "title", "title_english", "score", "members", "rank", "popularity", "episodes", "year", "status")}


def fandom(slug, terms, per_term=2, max_pages=7, cap=24000):
    api = f"https://{slug}.fandom.com/api.php"
    titles = []
    for t in terms:
        d = http_json(api + "?" + urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": t, "srlimit": per_term, "format": "json"}))
        for r in ((d or {}).get("query") or {}).get("search", []):
            if r["title"] not in titles:
                titles.append(r["title"])
    pages = []
    titles = [t for t in titles if not re.search(r"Gallery|Image|/Navigation", t)]  # صفحات الصور بلا معلومات
    for title in titles[:max_pages]:
        d = http_json(api + "?" + urllib.parse.urlencode({"action": "parse", "page": title, "prop": "text", "format": "json", "formatversion": 2, "redirects": 1}))
        txt = strip_html(((d or {}).get("parse") or {}).get("text", ""))
        if txt:
            url = f"https://{slug}.fandom.com/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            if len(txt) > cap:  # «معلومات إضافية» والمراجع في آخر الصفحة؛ نحتفظ بالبداية والنهاية
                txt = txt[: int(cap * 0.55)] + "\n[…]\n" + txt[-int(cap * 0.45):]
            pages.append({"title": title, "url": url, "text": txt})
    return pages


def fandom_trivia(slug, titles):
    """وضع السلسلة: لكل صفحة شخصية/موضوع يجلب المقدمة وقسم «معلومات إضافية» والمراجع فقط (حيث تسكن التفاصيل الخفية)."""
    api, out = f"https://{slug}.fandom.com/api.php", []
    for title in titles:
        q = lambda **k: http_json(api + "?" + urllib.parse.urlencode({"action": "parse", "format": "json", "formatversion": 2, "redirects": 1, **k}), tries=2)
        d = q(page=title, prop="sections")
        if not d or "parse" not in d:  # اسم غير مطابق: نأخذ أول نتيجة بحث
            r = http_json(api + "?" + urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": title, "srlimit": 1, "format": "json"}), tries=2)
            hits = ((r or {}).get("query") or {}).get("search", [])
            if not hits:
                continue
            title = hits[0]["title"]
            d = q(page=title, prop="sections")
            if not d or "parse" not in d:
                continue
        title = d["parse"].get("title", title)
        secs = {x["line"].strip().lower(): x["index"] for x in d["parse"].get("sections", [])}
        part = lambda i: strip_html(((q(page=title, prop="text", section=i) or {}).get("parse") or {}).get("text", ""))
        page = {"title": title, "url": f"https://{slug}.fandom.com/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                "intro": part(0)[:3000]}
        for name in ("trivia", "references"):
            if name in secs:
                page[name] = part(secs[name])[:12000]
        out.append(page)
        print(f"   {title}: معلومات إضافية {len(page.get('trivia', ''))} حرف", file=sys.stderr)
    return out


# ---------- استدعاءات Claude ----------
CLIENT = None
RAW_ONLY = False


def claude(system, prompt, tools=None, schema=None, effort="high", max_tokens=32000):
    """استدعاء واحد مع متابعة pause_turn؛ يعيد النص النهائي. أدوات الويب تعمل على خوادم Anthropic."""
    global CLIENT
    CLIENT = CLIENT or anthropic.Anthropic()
    messages = [{"role": "user", "content": prompt}]
    kw = {"output_config": {"effort": effort, **({"format": {"type": "json_schema", "schema": schema}} if schema else {})}}
    if tools:
        kw["tools"] = tools
    for _ in range(6):
        with CLIENT.beta.messages.stream(
            model=MODEL, max_tokens=max_tokens, system=system, messages=messages,
            thinking={"type": "adaptive"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw,
        ) as stream:
            r = stream.get_final_message()
        u = r.usage
        print(f"  ← {r.stop_reason} | دخل {u.input_tokens} خرج {u.output_tokens}", file=sys.stderr)
        if r.stop_reason == "refusal":
            sys.exit(f"رفض النموذج الطلب: {getattr(r.stop_details, 'category', None)}")
        if r.stop_reason == "pause_turn":  # جولة بحث طويلة توقفت مؤقتاً؛ تُستأنف كما هي
            messages = messages + [{"role": "assistant", "content": r.content}]
            continue
        if r.stop_reason == "max_tokens":
            sys.exit("انقطع الرد عند حد الطول؛ ارفع max_tokens")
        return "".join(b.text for b in r.content if b.type == "text")
    sys.exit("تجاوز عدد مرات الاستئناف")


def last_json(text):
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = blocks[-1] if blocks else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


SYS_RESEARCH = ("You are a meticulous anime/manga lore researcher building a fact dossier for short Arabic explainer videos. "
    "Fans scrutinise every detail, so accuracy beats quantity. " + NO_PIRACY)


def research(work, event, corpus):
    prompt = f"""Work: {work}
Event / question the video answers (Arabic): {event}

Below is raw material already collected (AniList, MyAnimeList, Fandom wiki pages). Use it, then use web_search and web_fetch
to go deeper: fetch the wiki pages for the specific chapters/episodes involved, the manga-vs-anime differences sections,
author interviews/Q&As (e.g. SBS, fanbook/databook notes as reported by wikis), and well-sourced fan analysis.

Find 8-12 details that MOST viewers of the anime missed and that make this event hit harder. Prioritise:
1. Foreshadowing: an early line, object, or panel whose meaning is revealed much later (give both chapter/episode numbers).
2. Anime vs manga: scenes cut, added, or changed, and what that changes.
3. Author or official statements (interviews, databooks, colour-spread notes, character profiles).
4. Name/word meanings in Japanese, visual symbols, colours, repeated motifs.
5. Hard numbers: chapter/episode, ages, dates, counts, rankings.

For every detail give: where it appears (chapter and/or episode), at least one source URL you actually saw,
and status "confirmed" (shown in the work or stated by the author/official material) or "theory" (fan interpretation).
Also collect 2-4 popular fan theories or widely repeated fan claims about this event (fan articles, forums, videos):
they hook viewers, so keep them with status "theory" and cite the fan source. Do not invent sources.

Also suggest 3 other high-interest event questions from this work that would make strong explainer videos.

End your answer with ONE ```json block exactly in this shape:
{{"work_en": "", "event_question_ar": "", "details": [{{"id": "d1", "claim_en": "", "claim_ar": "", "where": "", "type": "foreshadowing|anime_vs_manga|author|symbol|fact", "status": "confirmed|theory", "surprise": 1, "evidence": "", "sources": [""]}}], "other_event_ideas": [{{"question_ar": "", "why": ""}}]}}

surprise is 1-5: how likely a casual anime-only viewer is to say "I never noticed that".

=== RAW MATERIAL ===
{corpus}"""
    return last_json(claude(SYS_RESEARCH, prompt, tools=WEB_TOOLS))


SYS_VERIFY = ("You are an independent fact-checker for anime/manga lore. You did not write these claims. "
    "Check each one against its sources and your own searches; be strict. " + NO_PIRACY)


def verify(work, details):
    prompt = f"""Work: {work}
Check every detail below. Fetch the cited sources (web_fetch) and search further (web_search) when needed.
Verdicts:
- "keep": accurate as written, status correct, chapter/episode correct.
- "theory": interpretation or a fan claim not confirmed by the work or the author (fan articles count here, not as drop); say what is confirmed.
- "fix": mostly right but a fact (number, chapter, wording) must change; give corrected claim_en.
- "drop": contradicted by the work itself, or a source that does not exist. An unconfirmed fan claim is "theory", not "drop".

End with ONE ```json block: {{"checks": [{{"id": "d1", "verdict": "keep|theory|fix|drop", "corrected_claim_en": "", "note": "", "sources": [""]}}]}}

DETAILS:
{json.dumps(details, ensure_ascii=False, indent=1)}"""
    return last_json(claude(SYS_VERIFY, prompt, tools=WEB_TOOLS))


def merge(details, checks):
    by = {c["id"]: c for c in checks}
    kept = []
    for d in details:
        c = by.get(d["id"], {"verdict": "drop", "note": "لم يُفحص"})
        d = {**d, "verdict": c["verdict"], "check_note": c.get("note", ""), "sources": list(dict.fromkeys(d.get("sources", []) + c.get("sources", [])))}
        if c["verdict"] == "drop":
            continue
        if c["verdict"] == "theory":
            d["status"] = "theory"
        if c["verdict"] == "fix" and c.get("corrected_claim_en"):
            d["claim_en"], d["claim_ar"] = c["corrected_claim_en"], ""  # النص العربي يُعاد كتابته من المصحَّح
        kept.append(d)
    kept.sort(key=lambda d: (d["status"] != "confirmed", -int(d.get("surprise", 0))))
    return kept


SYS_SCRIPT = ("أنت كاتب مقاطع شرح قصيرة لقناة أنمي عربية. اكتب بالعربية بلهجة سعودية بيضاء. "
    "استعمل التفاصيل المعطاة فقط ولا تضف أي معلومة. ممنوع ذكر أي اسم تطبيق أو علامة تجارية؛ قل «التطبيق». "
    "الحرق مسموح. ميّز صراحةً بين ما أكدته القصة وما هو نظرية، وقدّم النظرية بعبارة مثل «فيه نظرية تقول...».")

SCRIPT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "primary_keyword", "hook", "speech", "overlay_line", "summary", "insight", "question", "tags", "suffix", "used_detail_ids", "detail_lines_ar"],
    "properties": {
        "title": {"type": "string"}, "primary_keyword": {"type": "string"}, "hook": {"type": "string"},
        "speech": {"type": "string"}, "overlay_line": {"type": "string"}, "summary": {"type": "string"},
        "insight": {"type": "string"}, "question": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}}, "suffix": {"type": "string"},
        "used_detail_ids": {"type": "array", "items": {"type": "string"}},
        "detail_lines_ar": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["id", "line_ar"], "properties": {"id": {"type": "string"}, "line_ar": {"type": "string"}}}},
    },
}


def script(work, work_ar, event, kept):
    prompt = f"""العمل: {work_ar} ({work})
سؤال المقطع: {event}

اكتب مقطع شرح بهذه البنية حرفياً (25 إلى 35 ثانية بالخاتمة، 55 إلى 65 كلمة في speech؛ المعلّق يقرأ نحو 2.2 كلمة بالثانية):
1. خطاف في 3 ثوانٍ: السؤال نفسه بلا مقدمات وبلا تحذير حرق.
2. وضع المشاهد: «تخيّل أنك...» أو «لو كنت مكانه...».
3. نقطتان أو ثلاث مرتبة من الدليل إلى النتيجة، كل نقطة تفصيل محدد من القائمة، والأفضل الأعلى مفاجأة والمؤكد. تُروى المعلومة حقيقة مباشرة، ولا يُذكر فصل ولا حلقة ولا مجلد ولا «المانغا» ولا «الأنمي» كمصدر.
4. الإقفال: جواب مختصر أو سؤال مفتوح، مع التمييز الصريح بين المؤكد والنظرية. أضف نظرية واحدة جذابة من القائمة إن وُجدت، بعبارة «فيه نظرية تقول...»، ولا تقدّمها كحقيقة.
5. التفاعل: سؤال محدد للتعليق ينتهي به النص «اكتب رأيك». طلب الإعجاب ودعوة التحميل تأتيان بعده في خاتمة موحّدة تضاف آلياً، فلا تكتبهما.
لا تكتب خاتمة التحميل ولا طلب الإعجاب؛ يضافان آلياً.

الحقول:
- title: أقل من 70 حرفاً، سؤال بعبارة البحث الأقوى، يحوي الاسم العربي والإنجليزي للعمل.
- primary_keyword: عبارة البحث العربية الأقوى، وآخر كلمة فيها تظهر حرفياً في العنوان.
- overlay_line: جملة الشاشة، 7 كلمات كحد أقصى.
- hook وsummary وinsight وquestion: لنصوص المنصات (insight = أقوى تفصيل خفي بجملة واحدة).
- tags: ثلاثة وسوم بالصيغة #كلمة، الأول إنجليزي باسم العمل.
- suffix: لاحقة قصيرة للعنوان مثل «أكازا والنساء».
- detail_lines_ar: لكل تفصيل في القائمة (كلها لا المستعملة فقط) سطر عربي دقيق قصير بنفس معناه.

التفاصيل المدقّقة (مرتبة: المؤكد أولاً ثم الأعلى مفاجأة):
{json.dumps(kept, ensure_ascii=False, indent=1)}"""
    return json.loads(claude(SYS_SCRIPT, prompt, schema=SCRIPT_SCHEMA, effort="medium", max_tokens=16000))


def wiki_terms(work, event):
    schema = {"type": "object", "additionalProperties": False, "required": ["terms"],
              "properties": {"terms": {"type": "array", "items": {"type": "string"}}}}
    p = f"Work: {work}\nArabic question: {event}\nGive 3-5 short English Fandom-wiki search terms (character names, arc, ability, event) for this question."
    return json.loads(claude("Return only the requested JSON.", p, schema=schema, effort="low", max_tokens=2000))["terms"]


# ---------- التقرير ----------
def report(d):
    s, L = d["script"], []
    L += [f"# ملف معلومات: {d['event']}", "", f"العمل: {d['work_ar']} — `{d['work']}`", ""]
    if d.get("stats"):
        L += ["## مؤشرات الاهتمام", "", "| المؤشر | القيمة |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in d["stats"].items() if v is not None] + [""]
    lines = {x["id"]: x["line_ar"] for x in s["detail_lines_ar"]}
    L += ["## التفاصيل بعد التدقيق", "", "| التفصيل | الموضع | الحالة | المفاجأة | المصادر |", "|---|---|---|---|---|"]
    for x in d["details"]:
        st = "مؤكد" if x["status"] == "confirmed" else "نظرية"
        used = " ✅" if x["id"] in s["used_detail_ids"] else ""
        src = " ".join(f"[{i + 1}]({u})" for i, u in enumerate(x["sources"][:3]))
        L.append(f"| {lines.get(x['id'], x['claim_en'])}{used} | {x.get('where', '')} | {st} | {x.get('surprise', '')} | {src} |")
    dropped = [c for c in d["checks"] if c["verdict"] == "drop"]
    L += ["", f"حُذف بعد التدقيق: {len(dropped)} تفصيل.", "", "## النص الجاهز", "",
          f"العنوان: {s['title']}", "", f"عبارة البحث: {s['primary_keyword']}", "", f"جملة الشاشة: {s['overlay_line']}", "",
          "التعليق الصوتي:", "", f"> {s['speech']}", "", f"عدد الكلمات: {len(s['speech'].split())}", "",
          "## أفكار مقاطع تالية من العمل نفسه", ""]
    L += [f"1. {i['question_ar']} — {i['why']}" for i in d.get("other_event_ideas", [])]
    L += ["", "## أمر الإضافة إلى قائمة الانتظار بعد المراجعة", "", "```bash",
          f'python tools/autoproduce/new_clip.py --key {d["key"]} --ar "{d["work_ar"]}" --en "{d["work"]}" '
          f'--hook "{s["hook"]}" --summary "{s["summary"]}" --insight "{s["insight"]}" --question "{s["question"]}" '
          f'--tags "{",".join(s["tags"][:3])}" --suffix "{s["suffix"]}" --url <رابط_اللقطة> --credit-name <المرجع> --rights <أصحاب_الحقوق>',
          "```", ""]
    return "\n".join(L)


SERIES = OUT / "series"


SOURCE_WORDS = re.compile(r"الفصل|المانغا|المانجا|الحلقة|المجلد")


def series_assemble(key):
    """المسار المجاني لسلسلة: Claude Code يكتب series/<key>.plan.json (pool + videos) ثم يُتحقق ويُبنى التقرير."""
    plan = json.loads((SERIES / f"{key}.plan.json").read_text(encoding="utf-8"))
    pool = {d["id"]: d for d in plan["pool"]}
    errs, used = [], {}
    for v in plan["videos"]:
        n, ids, sp = v["n"], v["detail_ids"], v["speech"]
        if len(ids) < 3:
            errs.append(f"{n}: أقل من 3 تفاصيل")
        for i in ids:
            if i not in pool:
                errs.append(f"{n}: تفصيل غير موجود {i}")
            used.setdefault(i, []).append(n)
        if any(pool.get(i, {}).get("status") == "theory" for i in ids) and "نظرية" not in sp:
            errs.append(f"{n}: يستعمل نظرية دون عبارة «نظرية»")
        w = len(sp.split())
        if v.get("style") == "v2":  # صيغة 20 نوفمبر 2026: أقصر، وبلا ذكر مصدر المعلومة
            if not 50 <= w <= 68:
                errs.append(f"{n}: {w} كلمة (المطلوب 55-65)")
            if SOURCE_WORDS.search(sp):
                errs.append(f"{n}: النص يذكر مصدراً (فصل أو حلقة أو مجلد أو مانغا)؛ تُروى المعلومة حقيقة مباشرة")
        elif not 85 <= w <= 135:
            errs.append(f"{n}: {w} كلمة (المطلوب 90-130)")
        if len(v["title"]) > 70:
            errs.append(f"{n}: العنوان {len(v['title'])} حرفاً")
        if v["primary_keyword"].split()[-1] not in v["title"]:
            errs.append(f"{n}: آخر كلمة من عبارة البحث غير ظاهرة في العنوان")
    errs += [f"التفصيل {i} مكرر في المقاطع {ns}" for i, ns in used.items() if len(ns) > 1]
    if errs:
        sys.exit("أخطاء الخطة:\n" + "\n".join(errs))
    plan["unused_pool"] = [i for i in pool if i not in used]
    (SERIES / f"{key}.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    L = [f"# سلسلة {plan['work_ar']}: {len(plan['videos'])} مقطعاً", "",
         f"مخزون التفاصيل: {len(pool)}، منها نظريات: {sum(d['status'] == 'theory' for d in pool.values())}، وغير المستعمل: {len(plan['unused_pool'])}.", ""]
    for v in plan["videos"]:
        L += [f"## المقطع {v['n']}: {v['question']}", "", f"العنوان: {v['title']}", "", f"جملة الشاشة: {v['overlay_line']}", "", "التفاصيل:", ""]
        for i in v["detail_ids"]:
            d = pool[i]
            tag = "نظرية" if d["status"] == "theory" else "مؤكد"
            src = " ".join(f"[{k + 1}]({u})" for k, u in enumerate(d["sources"][:2]))
            L.append(f"1. {d['claim_ar']} — {tag}، {d.get('where', '')} {src}")
        L += ["", f"> {v['speech']}", ""]
    (SERIES / f"{key}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"سليمة: {len(plan['videos'])} مقطعاً، {len(used)} تفصيلاً مستعملاً")


def stats_of(al, mal):
    st = {}
    if al:
        st.update({"شعبية AniList": al.get("popularity"), "مفضلة AniList": al.get("favourites"), "رواج AniList الآن": al.get("trending")})
    if mal:
        st.update({"أعضاء MyAnimeList": mal.get("members"), "تقييم MyAnimeList": mal.get("score")})
    return st


def write(d):
    (OUT / f"{d['key']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = report(d)
    (OUT / f"{d['key']}.md").write_text(md, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)


def assemble(key):
    """المسار المجاني: Claude Code يكتب <key>.manual.json (details, checks, script, other_event_ideas) بعد بحثه وتدقيقه."""
    raw = json.loads((OUT / f"{key}.raw.json").read_text(encoding="utf-8"))
    m = json.loads((OUT / f"{key}.manual.json").read_text(encoding="utf-8"))
    write({"key": key, "work": raw["work"], "work_ar": raw["work_ar"], "event": raw["event"], "model": "claude-code-session",
           "wiki": raw["wiki"], "terms": raw["terms"], "stats": stats_of(raw.get("anilist"), raw.get("myanimelist")),
           "wiki_pages": [{"title": p["title"], "url": p["url"]} for p in raw["wiki_pages"]],
           "raw_details": m["details"], "checks": m["checks"], "details": merge(m["details"], m["checks"]),
           "other_event_ideas": m.get("other_event_ideas", []), "script": m["script"]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default="", help="ملف JSON بقائمة أعمال (key, work, work_ar, event, terms, wiki, enabled)")
    ap.add_argument("--only", default="", help="مع --jobs: مفتاح واحد فقط")
    ap.add_argument("--key")
    ap.add_argument("--work", help="الاسم الإنجليزي للعمل")
    ap.add_argument("--work-ar", default="")
    ap.add_argument("--event", help="سؤال الحدث بالعربية")
    ap.add_argument("--terms", default="", help="كلمات بحث إنجليزية للويكي مفصولة بفواصل")
    ap.add_argument("--wiki", default="", help="اسم ويكي Fandom إن لم يكن في القائمة")
    ap.add_argument("--assemble", default="", help="مفتاح: يبني <key>.json و.md من <key>.manual.json (بحث Claude Code المجاني) و<key>.raw.json")
    ap.add_argument("--series-assemble", default="", help="مفتاح سلسلة: يتحقق من series/<key>.plan.json ويبني التقرير")
    ap.add_argument("--raw-only", action="store_true", help="المرحلة 1 فقط بلا مفتاح: يحفظ <key>.raw.json ليكمل Claude Code المسار المجاني")
    a = ap.parse_args()
    if a.assemble:
        return assemble(a.assemble)
    if a.series_assemble:
        return series_assemble(a.series_assemble)
    global RAW_ONLY
    RAW_ONLY = a.raw_only or not os.environ.get("ANTHROPIC_API_KEY")
    if RAW_ONLY:
        print("وضع الجمع الخام فقط (بلا مفتاح Claude API)", file=sys.stderr)
    OUT.mkdir(exist_ok=True)
    if a.jobs:
        jobs = [j for j in json.loads(Path(a.jobs).read_text(encoding="utf-8")) if j.get("enabled", True) and (not a.only or j["key"] == a.only)]
        failed = []
        for j in jobs:
            print(f"\n===== {j['key']} =====", file=sys.stderr)
            if j.get("series"):  # سلسلة: مخزون تفاصيل من صفحات كثيرة، بلا بحث مدفوع
                SERIES.mkdir(parents=True, exist_ok=True)
                slug = j.get("wiki") or WIKIS.get(j["work"].lower())
                raw = {k: j.get(k) for k in ("key", "work", "work_ar")} | {"wiki": slug, "anilist": anilist(j["work"]),
                       "pages": fandom_trivia(slug, j["pages"])}
                (SERIES / f"{j['key']}.raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                continue
            try:
                run(argparse.Namespace(key=j["key"], work=j["work"], work_ar=j.get("work_ar", ""), event=j["event"],
                                       terms=j.get("terms", ""), wiki=j.get("wiki", "")))
            except (SystemExit, Exception) as e:  # فشل عمل لا يوقف البقية
                print(f"فشل {j['key']}: {e}", file=sys.stderr)
                failed.append(j["key"])
        if failed:
            sys.exit(f"فشلت: {', '.join(failed)}")
        return
    if not (a.key and a.work and a.event):
        ap.error("--key و--work و--event مطلوبة بدون --jobs")
    run(a)


def run(a):

    print("1/4 جمع خام مجاني…", file=sys.stderr)
    terms = [t.strip() for t in a.terms.split(",") if t.strip()] or ([a.work] if RAW_ONLY else wiki_terms(a.work, a.event))
    slug = a.wiki or WIKIS.get(a.work.lower()) or re.sub(r"[^a-z0-9]", "", a.work.lower())
    al, mal, pages = anilist(a.work), jikan(a.work), fandom(slug, terms)
    work_ar = a.work_ar or a.work
    corpus = json.dumps({"anilist": al, "myanimelist": mal}, ensure_ascii=False)[:20000]
    for p in pages:
        corpus += f"\n\n--- WIKI PAGE: {p['title']} ({p['url']}) ---\n{p['text']}"
    print(f"   ويكي {slug}: {len(pages)} صفحة، {len(corpus)} حرف", file=sys.stderr)
    if RAW_ONLY:
        raw = {"key": a.key, "work": a.work, "work_ar": work_ar, "event": a.event, "wiki": slug, "terms": terms,
               "anilist": al, "myanimelist": mal, "wiki_pages": pages}
        (OUT / f"{a.key}.raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"حُفظ {a.key}.raw.json", file=sys.stderr)
        return

    print("2/4 بحث موسّع…", file=sys.stderr)
    r = research(a.work, a.event, corpus)
    print(f"3/4 تدقيق {len(r['details'])} تفصيل…", file=sys.stderr)
    checks = verify(a.work, r["details"])["checks"]
    kept = merge(r["details"], checks)
    if len(kept) < 3:
        sys.exit(f"بقي {len(kept)} تفاصيل فقط بعد التدقيق؛ الحدث لا يكفي لمقطع شرح")
    print(f"4/4 كتابة النص من {len(kept)} تفصيل…", file=sys.stderr)
    s = script(a.work, work_ar, a.event, kept)

    write({"key": a.key, "work": a.work, "work_ar": work_ar, "event": a.event, "model": MODEL, "wiki": slug, "terms": terms,
           "stats": stats_of(al, mal), "wiki_pages": [{"title": p["title"], "url": p["url"]} for p in pages],
           "raw_details": r["details"], "checks": checks, "details": kept, "other_event_ideas": r.get("other_event_ideas", []), "script": s})


if __name__ == "__main__":
    main()
