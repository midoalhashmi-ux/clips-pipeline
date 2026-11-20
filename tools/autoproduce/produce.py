"""خط إنتاج المقاطع القصيرة: Claude للنص، Gemini للصوت فقط، ffmpeg للتركيب.
يخرج لكل عمل مجلداً فيه video.mp4 وmeta.txt جاهزين للرفع اليدوي."""
import argparse, base64, datetime, hashlib, json, os, re, shutil, subprocess, sys, time, urllib.request, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
OUTRO_CACHE = ROOT / "outro_cache"  # صوت الخاتمة المولَّد مسبقاً (ذاكرة سير العمل المؤقتة)
# توجيه أداء بأسلوب «مخرج صوت» (طلب المالك 20 نوفمبر 2026: صوت سعودي بمشاعر يظنه المشاهد إنساناً حقيقياً).
# البنية الموصى بها لـ Gemini TTS: ملف الصوت، المشهد، ملاحظات المخرج، ثم النص الحرفي.
VOICE_DIRECTION = """# AUDIO PROFILE
A Saudi man in his late twenties, a popular anime storyteller on social media, recording on his own microphone at home.
Warm, slightly deep, relaxed voice. White Saudi (Najdi-neutral) Arabic dialect, natural everyday pronunciation, never formal classical Arabic.

## SCENE
Late at night, he is telling a close friend a secret about an anime that most fans missed. Intimate, genuinely excited, human.

### DIRECTOR'S NOTES
- Opening question: lower, intriguing, as if leaning in; a short natural pause after it.
- The line that starts with "تخيّل": slower and softer, pulling the listener into the moment.
- The facts: build energy step by step; stress the one surprising word in each sentence; vary the pace like real conversation, with small breaths and micro-pauses between sentences.
- Any sentence with "نظرية": a little playful and less certain.
- Any sentence with "المؤكد": calm and confident.
- The final question: warm and inviting, you can hear a smile.
- Sound like a real person, not an announcer and not a robot; no exaggerated drama.
- Read the Arabic transcript exactly as written, every word, nothing added, nothing skipped. Never read these notes.

#### TRANSCRIPT"""
OUTRO_DIRECTION = """# AUDIO PROFILE
The same Saudi storyteller, warm and friendly, white Saudi dialect.

### DIRECTOR'S NOTES
- A quick, friendly call to action, smiling, like recommending something to a friend. Natural, not salesy.
- Read the Arabic transcript exactly as written. Never read these notes.

#### TRANSCRIPT"""
VOICE_NAME = os.environ.get("VOICE_NAME", "Charon")  # الصوت المعتمد من المالك


def polish_voice(wav):
    """معالجة استوديو خفيفة: إزالة الطنين المنخفض، ضغط لطيف، ومستوى صوت مناسب للمنصات."""
    tmp = Path(str(wav) + ".p.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af",
        "highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=10:release=200:makeup=2,loudnorm=I=-16:TP=-1.5:LRA=9",
        "-ar", "24000", "-ac", "1", str(tmp)], check=True)
    tmp.replace(wav)


SYSTEM = ("أنت كاتب محتوى قصير لقناة ترشيحات أنمي ومسلسلات وأفلام. اكتب بالعربية بلهجة سعودية بيضاء. "
    "التزم بالحقائق المعطاة في synopsis فقط ولا تخترع أي معلومة أو اسم أو حدث؛ إن نقصت المعلومات "
    "فاكتب جملاً عامة صحيحة بلا تفاصيل غير مؤكدة. ممنوع ذكر أي اسم تطبيق أو علامة تجارية؛ "
    "استخدم عبارة «تطبيق مشاهدة» أو «التطبيق». الحرق مسموح. أعد JSON فقط بلا أي نص آخر.")


def claude_text(item):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY غير موجود في أسرار المستودع")
    prompt = (f"العمل: {item['display_title']} ({item.get('english_title','')})، النوع: {item['type']}.\n"
        f"synopsis: {item.get('synopsis','(لا يوجد)')}\n\n"
        'أعد JSON بهذا الشكل: {"speech": "نص التعليق الصوتي 35-45 كلمة يفتح بجملة جاذبة", '
        '"title": "عنوان يوتيوب أقل من 70 حرفاً", "description": "وصف من فقرتين قصيرتين", '
        '"tags": ["وسم1","وسم2"], "short_caption": "تعليق قصير لإنستقرام وفيسبوك وتيك توك مع 5 وسوم"}')
    body = json.dumps({"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 1500,
        "system": SYSTEM, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", body, {
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.load(r)["content"][0]["text"]
    return json.loads(re.search(r"\{.*\}", text, re.S).group(0))


QUOTA = {"out": False}


def gemini_voice(speech, wav_path, direction=None):
    if QUOTA["out"]:
        sys.exit("حصة Gemini المجانية اليومية نفدت؛ أعد التشغيل غداً")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY غير موجود في أسرار المستودع")
    last = None
    for model in ("gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"):
        body = json.dumps({"contents": [{"parts": [{"text": (direction or VOICE_DIRECTION) + "\n" + speech}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": VOICE_NAME}}}}}).encode()
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", body,
            {"x-goog-api-key": key, "content-type": "application/json"})
        for attempt in range(3):  # 429 = حد المعدل؛ ننتظر ثم نعيد
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    pcm = base64.b64decode(json.load(r)["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
                with wave.open(str(wav_path), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
                return
            except Exception as e:
                last = e
                if "429" in str(e) and attempt < 2:
                    time.sleep(30 * (attempt + 1))
                else:
                    break
    if "429" in str(last):
        QUOTA["out"] = True
    sys.exit(f"فشل توليد الصوت: {last}")


MAX_MAIN_SECONDS = 28.0  # الصوت قبل الخاتمة؛ مع الخاتمة (نحو 6 ثوانٍ) يبقى المقطع تحت 35 ثانية
MIN_SOURCE_HEIGHT = 720  # طلب المالك 20 نوفمبر 2026: لا مصدر أقل من 720p، والمفضّل 1080p فأعلى
PREFERRED_SOURCE_HEIGHT = 1080


def best_rendition(url):
    """رابط theplatform الافتراضي قد يعيد نسخة صغيرة (234p لإعلاني ون بيس القديمين)؛ نختار أعلى دقة من ملف SMIL."""
    if "theplatform.com" not in url:
        return url
    try:
        smil_url = url + ("&" if "?" in url else "?") + "format=SMIL"
        smil = urllib.request.urlopen(smil_url, timeout=30).read().decode("utf-8", "ignore")
    except Exception:
        return url
    best = None
    for tag in re.findall(r"<video\b[^>]*>", smil):
        src, h, b = (re.search(p, tag) for p in (r'src="([^"]+)"', r'height="(\d+)"', r'system-bitrate="(\d+)"'))
        if not (src and h):
            continue
        key = (int(h.group(1)), int(b.group(1)) if b else 0)
        if best is None or key > best[0]:
            best = (key, src.group(1).replace("&amp;", "&"))
    return best[1] if best else url


def check_quality(path):
    """يرفض أي مصدر أقل من 720p، ويحذّر إن كان أقل من 1080p."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
        "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip().split(",")
    w, h = int(out[0]), int(out[1])
    short = min(w, h)
    if short < MIN_SOURCE_HEIGHT:
        raise SystemExit(f"جودة المصدر {w}x{h} أقل من {MIN_SOURCE_HEIGHT}p ممنوعة؛ اختر مصدراً بجودة 1080p أو أعلى")
    if short < PREFERRED_SOURCE_HEIGHT:
        print(f"تنبيه: جودة المصدر {w}x{h}؛ المفضّل 1080p فأعلى")
    else:
        print(f"جودة المصدر {w}x{h} سليمة")


def build_montage(item, d, target=None):
    """مقاطع متعددة تناسب القصة (طلب المالك 20 نوفمبر 2026): كل مقطع في `segments` له `url` اختياري (الافتراضي مصدر العمل)
    و`start` و`dur` و`shows` (ما يظهر فيه). تُقصّ وتُدمج بالترتيب بحجم 1920x1080 بلا صوت، ثم تُستعمل كمصدر واحد."""
    cache, parts = {}, []
    total = sum(float(sg["dur"]) for sg in item["segments"]) or 1.0
    # تتمدد اللقطات أو تنكمش معاً لتطابق طول الصوت (بين 0.8 و1.25)، فتبقى كل لقطة على جملتها
    factor = min(1.25, max(0.8, target / total)) if target else 1.0
    for i, seg in enumerate(item["segments"]):
        url = seg.get("url") or item["source_url"]
        if url not in cache:
            f = d / f"_src{len(cache)}.mp4"
            fetch_source({"source_url": url}, f); check_quality(f)
            cache[url] = f
        out = d / f"_seg{i}.mp4"
        # لا نخرج عن النافذة المراجَعة أبداً: الإطالة تكون بإبطاء خفيف للّقطة نفسها، والتقصير بقصّها
        dur = float(seg["dur"]) * min(factor, 1.0)
        slow = f"setpts={factor:.3f}*PTS," if factor > 1.0 else ""
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{float(seg['start']):.2f}", "-t", f"{dur:.2f}",
            "-i", str(cache[url]), "-vf", f"{slow}scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=30",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out)], check=True)
        parts.append(out)
    lst = d / "_montage.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
    montage = d / "source.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(montage)], check=True)
    for p in [*parts, *cache.values(), lst]:
        p.unlink()
    return montage


def fetch_source(item, dest):
    url = item["source_url"]
    if url.lower().endswith(".mp4") or "theplatform.com" in url:
        urllib.request.urlretrieve(best_rendition(url), dest)
    else:
        subprocess.run(["yt-dlp", "-f", "bv*[height>=1080]+ba/bv*[height>=720]+ba/b[height>=720]", "--merge-output-format", "mp4",
            "-o", str(dest), url], check=True)


ACCENTS = ["#a8f36a", "#b29aff", "#ffb668", "#6ad6ff", "#ff8fa3", "#ffd86a"]  # ألوان أعمال سابقة (خضراء أولاً)
FONT = ROOT / "fonts" / "Cairo-Variable.ttf"  # الخط نفسه المستعمل بالفيديوهات المعتمدة (Cairo)


def font(size, weight=800):
    from PIL import ImageFont
    face = ImageFont.truetype(str(FONT), size)
    face.set_variation_by_axes([weight, 0])
    return face


def split_chunks(speech, maxw=5):
    """جمل قصيرة: نقطع عند علامات الوقف ثم نوزّع الكلمات بالتساوي (حد أقصى maxw كلمات)."""
    parts = [x.strip() for x in re.split(r"(?<=[.!؟?…،,])\s+", speech.replace("...", "…")) if x.strip()]
    chunks = []
    for part in parts:
        words = part.split()
        n = -(-len(words) // maxw)
        size = -(-len(words) // n)
        chunks += [" ".join(words[k:k + size]) for k in range(0, len(words), size)]
    return chunks or [speech]


def draw_ar(draw, xy, text, face, **kw):
    draw.text(xy, text, font=face, anchor="mt", direction="rtl", language="ar", **kw)


def ar_width(draw, text, face):
    b = draw.textbbox((0, 0), text, font=face, direction="rtl", language="ar")
    return b[2] - b[0]


def make_overlay(item, chunk, accent, path):
    """نفس أسلوب الفيديوهات المعتمدة: عنوان بلون العمل أعلى، وجملة بيضاء كبيرة أسفل بلا تشتيت."""
    from PIL import Image, ImageDraw, features
    if not features.check("raqm"):
        sys.exit("مكتبة raqm غير متوفرة لـPillow (تشكيل العربية)؛ ثبّت libraqm0")
    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    g = ImageDraw.Draw(im)
    for y in range(1920):  # تدرج خفيف أعلى وأسفل الصورة
        op = 0
        if y < 400:
            op = round(170 * (1 - y / 400))
        if y > 1120:
            op = max(op, round(min(205, (y - 1120) * .33)))
        if y > 1660:
            op = max(op, round(min(255, 205 + (y - 1660) * .5)))
        if op:
            g.line((0, y, 1080, y), fill=(4, 7, 14, op))
    g.rounded_rectangle((90, 205, 98, 335), radius=4, fill=accent)
    draw_ar(g, (510, 210), item["display_title"], font(54), fill=accent, stroke_width=2, stroke_fill="#070b12")
    if item.get("english_title"):
        g.text((510, 292), item["english_title"].upper(), font=font(31, 650), anchor="mt", fill="white")
    g.rounded_rectangle((372, 1240, 648, 1247), radius=3, fill=accent)
    text = chunk.replace("...", "…")
    size = 86
    while True:  # سطر واحد إن اتسع، وإلا سطران متوازنان، مع تصغير الخط عند الحاجة
        face = font(size)
        words = text.split()
        lines = [text]
        if ar_width(g, text, face) > 880 and len(words) > 1:
            k = len(words) // 2
            lines = [" ".join(words[:k]), " ".join(words[k:])]
        if all(ar_width(g, ln, face) <= 880 for ln in lines) or size <= 56:
            break
        size -= 4
    words_all = text.split()
    clean = lambda w: w.strip("؟!.،…?")
    key = max(range(len(words_all)), key=lambda k: len(clean(words_all[k]))) if len(words_all) > 1 else -1
    y = 1305 if len(lines) > 1 else 1370
    idx = 0
    sp = face.getlength(" ") + 4
    for ln in lines:  # الكلمة المفتاحية (الأطول) بلون العمل لجاذبية أعلى، والباقي أبيض
        ws = ln.split()
        wd = [ar_width(g, w, face) for w in ws]
        x = 540 + (sum(wd) + sp * (len(ws) - 1)) / 2
        for w, d in zip(ws, wd):
            x -= d
            g.text((x, y), w, font=face, anchor="lt", direction="rtl", language="ar",
                   fill=accent if idx == key and len(clean(w)) >= 4 else "white", stroke_width=4, stroke_fill="#070b12")
            x -= sp; idx += 1
        y += size * 1.38
    im.save(path)


def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def has_audio(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return bool(r.stdout.strip())


def build_video(src, wav, out, item=None, d=None, segs=None):
    with wave.open(str(wav)) as w:
        vdur = w.getnframes() / w.getframerate()
    dur = vdur + 1.0
    capdur = dur  # نهاية ظهور الكتابة
    mode = (item or {}).get("audio_mode", "voice")  # voice | mix | hook
    if mode != "voice" and not has_audio(src):
        mode = "voice"
    if mode == "hook":  # التعليق افتتاحية فقط، ثم يستمر صوت المقطع الأصلي كاملاً
        dur += float((item or {}).get("tail", 12))
    if segs:  # الصوت المركّب يحوي الفجوات والذيل: طول الفيديو = طول الصوت
        dur = capdur = vdur
    sd = probe_duration(src)
    start = float((item or {}).get("clip_start", -1))
    if start >= 0:  # لا نبدأ بعد نهاية المصدر
        start = min(start, max(0.0, sd - dur - 1))
    if start < 0:  # نتجاوز الشعارات بالبداية وبطاقة التاريخ بالنهاية
        start = sd * 0.12 if sd > dur + 15 else max(0.0, min(sd * 0.12, sd - dur - 4))
    overlays = []
    if item and d:
        accent = item.get("accent") or ACCENTS[sum(map(ord, item["key"])) % len(ACCENTS)]
        n = 0
        for text, t0, t1 in (segs or [(item.get("speech", ""), 0.2, None)]):
            chunks = split_chunks(text)
            total = sum(len(c) for c in chunks)
            span = (t1 if t1 else vdur) - t0
            t = t0
            for k, c in enumerate(chunks):
                end = (t1 if t1 else capdur) if k == len(chunks) - 1 else t + span * len(c) / total
                png = d / f"_cap{n}.png"; n += 1; make_overlay(item, c, accent, png)
                overlays.append((png, t, end)); t = end
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-stream_loop", "-1", "-i", str(src), "-i", str(wav)]
    f = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30[v0]"
    last = "v0"
    if overlays:  # مسار شفاف واحد من الصور (concat) بمرحلة overlay واحدة، لسرعة الإنتاج مع الجمل الكثيرة
        from PIL import Image
        blank = d / "_blank.png"; Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)).save(blank)
        lines, cur = ["ffconcat version 1.0"], 0.0
        for png, a, b in overlays:
            if a > cur + 0.001:
                lines += [f"file '{blank}'", f"duration {a - cur:.3f}"]
            lines += [f"file '{png}'", f"duration {b - a:.3f}"]; cur = b
        lines.append(f"file '{overlays[-1][0]}'")
        lst = d / "_caps.ffconcat"; lst.write_text("\n".join(lines), encoding="utf-8")
        cmd += ["-f", "concat", "-safe", "0", "-i", str(lst)]
        f += ";[2:v]fps=30,format=rgba[ov];[v0][ov]overlay=0:0:eof_action=pass[v1]"
        last = "v1"
    amap = "1:a:0"
    if mode in ("mix", "hook"):  # صوت المقطع يخفت تلقائياً تحت التعليق ثم يعود كاملاً
        f += (";[1:a]apad,asplit=2[vo][sc];[0:a]volume=1.0[bg0];"
              "[bg0][sc]sidechaincompress=threshold=0.015:ratio=10:attack=15:release=350[bg];"
              "[bg][vo]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[am]")
        amap = "[am]"
    cmd += ["-filter_complex", f, "-map", f"[{last}]", "-map", amap, "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "1", str(out)]
    subprocess.run(cmd, check=True)
    for png, _, _ in overlays:
        png.unlink()
    if overlays:
        (d / "_blank.png").unlink(); (d / "_caps.ffconcat").unlink()


POLICY = ROOT.parent.parent / "docs/marketing/publishing-policy.json"


def outro_platforms():
    """منصات لها صورة خاتمة حقيقية في outro/ ونص خاتمة معتمد بسياسة النشر."""
    texts = json.loads(POLICY.read_text(encoding="utf-8"))["download_outros"]
    return {p: t for p, t in texts.items() if (ROOT / "outro" / f"{p}.png").exists()}


def build_outro(png, wav, out, cap=6.0):
    with wave.open(str(wav)) as w:
        sp = w.getnframes() / w.getframerate()
    tempo = min(1.25, max(1.0, sp / (cap - 0.5)))  # تسريع طفيف فقط إن زاد الصوت عن الحد
    dur = min(cap, sp / tempo + 0.5)
    bg = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30,setsar=1[bg]"
    fg = "scale=1000:-2:force_original_aspect_ratio=decrease[fg]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-i", str(wav),
        "-t", f"{dur:.2f}", "-filter_complex",
        f"[0:v]split[a][b];[a]{bg};[b]{fg};[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v];[1:a]atempo={tempo:.3f}[au]",
        "-map", "[v]", "-map", "[au]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-ar", "44100", "-ac", "1", str(out)], check=True)


def concat(main_mp4, outro_mp4, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(main_mp4), "-i", str(outro_mp4),
        "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", str(out)], check=True)


def wav_dur(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def fit_wav(src, dst, mx):
    """يسرّع الصوت طفيفاً (حتى 1.25x) إن زاد عن الحد الأقصى بالثواني."""
    dd = wav_dur(src)
    tempo = min(1.25, max(1.0, dd / mx))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", f"atempo={tempo:.3f}",
        "-ar", "24000", "-ac", "1", str(dst)], check=True)
    if wav_dur(dst) > mx + 0.3:
        print(f"تنبيه: المقطع الصوتي {wav_dur(dst):.1f}ث أطول من الحد {mx}ث؛ اختصر النص")
    return dst


def make_voice_segments(it, d, a, wav):
    """افتتاحية (حتى 5ث) ثم فجوة بصوت المقطع الأصلي ثم معلومة وسؤال تفاعل قبل الخاتمة. يرجع قائمة (نص، بداية، نهاية)."""
    parts = []
    for key, name, mx in (("speech", "hook", 5.0), ("speech_end", "end", 8.0)):
        raw = d / f"_{name}.wav"
        if a.dry_run:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                f"sine=frequency={300 if name == 'hook' else 400}:duration={4 if name == 'hook' else 6}",
                "-ar", "24000", "-ac", "1", str(raw)], check=True)
        else:
            gemini_voice(it[key], raw)
        parts.append(fit_wav(raw, d / f"_{name}f.wav", mx)); raw.unlink()
    gap = float(it.get("tail", 12))
    t0 = 0.2; t1 = t0 + wav_dur(parts[0]); t2 = t1 + gap; t3 = t2 + wav_dur(parts[1]); total = t3 + 0.6
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(parts[0]), "-i", str(parts[1]), "-filter_complex",
        f"[0:a]adelay={int(t0*1000)}|{int(t0*1000)}[a];[1:a]adelay={int(t2*1000)}|{int(t2*1000)}[b];"
        f"[a][b]amix=inputs=2:duration=longest:normalize=0,apad=whole_dur={total:.3f}[o]",
        "-map", "[o]", "-t", f"{total:.3f}", "-ar", "24000", "-ac", "1", str(wav)], check=True)
    for q in parts:
        q.unlink()
    return [(it["speech"], t0, t1), (it["speech_end"], t2, t3)]


def produce_item(it, a):
    segs = None
    d = OUT / f"{it['date']}-{it['key']}"
    d.mkdir(parents=True, exist_ok=True)
    if a.dry_run:
        meta = {"title": it["display_title"], "description": "dry-run", "tags": [], "short_caption": "dry-run", "speech": it.get("speech", "")}
        wav = d / "voice.wav"
        if it.get("speech_end"):
            segs = make_voice_segments(it, d, a, wav)
        else:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=14",
                "-ar", "24000", "-ac", "1", str(wav)], check=True)
        src = d / "source.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=40",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=40", "-pix_fmt", "yuv420p", "-shortest", str(src)], check=True)
    else:
        meta = it if it.get("speech") else claude_text(it)  # نص مكتوب مسبقاً = بلا API
        wav = d / "voice.wav"
        if it.get("speech_end"):
            segs = make_voice_segments(it, d, a, wav)
        else:
            vkey = OUTRO_CACHE / f"voice-{hashlib.sha1((VOICE_NAME + VOICE_DIRECTION + meta['speech']).encode()).hexdigest()[:16]}.wav"
            if vkey.exists():  # النص نفسه سبق توليده: لا نستهلك حصة الصوت عند تعديل اللقطات فقط
                shutil.copy(vkey, wav); print("صوت محفوظ مسبقاً:", vkey.name)
            else:
                gemini_voice(meta["speech"], wav)
                OUTRO_CACHE.mkdir(parents=True, exist_ok=True); shutil.copy(wav, vkey)
            if it.get("format") == "explainer" and wav_dur(wav) > MAX_MAIN_SECONDS:
                # طلب المالك 20 نوفمبر 2026: المقطع 25 إلى 35 ثانية بالخاتمة؛ يُسرَّع الصوت حتى 1.25 إن طال
                fitted = d / "voice_fit.wav"; fit_wav(wav, fitted, MAX_MAIN_SECONDS); fitted.replace(wav)
            polish_voice(wav)
        if it.get("segments"):
            src = build_montage(it, d, target=wav_dur(wav) + 1.0)
        else:
            src = d / "source.mp4"; fetch_source(it, src); check_quality(src)
    build_video(src, wav, d / "video.mp4", {**meta, **{k: it[k] for k in ("key", "display_title", "english_title", "accent", "clip_start", "audio_mode", "tail") if k in it},
        **({"clip_start": 0.0} if it.get("segments") else {})}, d, segs)
    (d / "meta.txt").write_text(
        f"العنوان:\n{meta['title']}\n\nالوصف:\n{meta['description']}\n\nالوسوم:\n{', '.join(meta['tags'])}\n\n"
        f"تعليق المنصات الأخرى:\n{meta['short_caption']}\n\nالنص المنطوق:\n{meta.get('speech','')}\n"
        + (f"\nمعلومة وتفاعل قبل الخاتمة:\n{it['speech_end']}\n" if it.get("speech_end") else "")
        + (f"\nمرجع اللقطات (يُذكر بالوصف):\n{it['source_credit']}\n" if it.get("source_credit") else ""), encoding="utf-8")
    src.unlink(); wav.unlink()
    plats = outro_platforms()
    if not plats:
        print("تنبيه: لا صور خاتمة في tools/autoproduce/outro/ فلا نسخ لكل منصة")
    for plat, text in plats.items():
        ow = OUT / f"_outro-{plat}.wav"
        if not ow.exists():  # صوت الخاتمة يُولَّد مرة واحدة ثم يُحفظ بالذاكرة المؤقتة، فلا يستهلك حصة الصوت مع كل مقطع
            if a.dry_run:
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=3",
                    "-ar", "24000", "-ac", "1", str(ow)], check=True)
            else:
                cached = OUTRO_CACHE / f"{plat}-v2-{hashlib.sha1(text.encode()).hexdigest()[:10]}.wav"
                if cached.exists():
                    shutil.copy(cached, ow)
                else:
                    gemini_voice(text, ow, OUTRO_DIRECTION); polish_voice(ow)
                    OUTRO_CACHE.mkdir(parents=True, exist_ok=True)
                    shutil.copy(ow, cached)
        build_outro(ROOT / "outro" / f"{plat}.png", ow, d / f"outro-{plat}.mp4")
        concat(d / "video.mp4", d / f"outro-{plat}.mp4", d / f"video-{plat}.mp4")
        (d / f"outro-{plat}.mp4").unlink()
    print("جاهز:", d.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="نافذة التواريخ القادمة")
    ap.add_argument("--dry-run", action="store_true", help="اختبار التركيب بلا مفاتيح")
    ap.add_argument("--only", default="", help="مفتاح عمل واحد فقط (يتجاوز نافذة التواريخ)")
    a = ap.parse_args()
    today = datetime.date.today()
    allq = json.loads((ROOT / "queue.json").read_text(encoding="utf-8"))
    if a.only:
        items = [i for i in allq if i["key"] == a.only]
    else:
        items = [i for i in allq
                 if i.get("enabled") and today <= datetime.date.fromisoformat(i["date"]) < today + datetime.timedelta(days=a.days)]
    if not items:
        print("لا أعمال مفعّلة بتواريخ الأسبوع القادم في queue.json"); return
    failed = []
    for it in items:
        try:
            produce_item(it, a)
        except (Exception, SystemExit) as e:
            print("فشل:", it["key"], e)
            shutil.rmtree(OUT / f"{it['date']}-{it['key']}", ignore_errors=True)
            failed.append(it["key"])
    for f in OUT.glob("_outro-*.wav"):
        f.unlink()
    if failed:
        sys.exit("أعمال فشلت: " + ", ".join(failed))



if __name__ == "__main__":
    main()
