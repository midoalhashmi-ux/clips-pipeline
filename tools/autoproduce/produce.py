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
A professional Saudi voice-over artist in his early thirties, the narrator of the most popular Arabic anime explainer channel.
Rich, resonant, charismatic voice. White Saudi (Najdi-neutral) Arabic dialect, natural pronunciation, never formal classical Arabic.

## SCENE
In a treated recording studio, he narrates a viral short about an anime secret he truly loves. He has one second to grab a scrolling viewer and must keep them until the end.

### DIRECTOR'S NOTES
- Energy: high but controlled, like a movie-trailer narrator who is also a passionate fan.
- Pace: fast-talking, noticeably faster than normal conversation, like the top short-form narrators, yet every word stays clear and natural. Keep pauses very short; the only real pause is the dramatic beat before the reveal.
- Opening question: punchy and intriguing, with a slight rise; then a short dramatic beat.
- Build tension sentence by sentence. Just before the key reveal, slow down and drop to a lower, almost whispered tone; then deliver the reveal with weight and a confident smile.
- Let the emotion follow the meaning: awe for great power, heaviness for loss or death, menace for villains, playful doubt for any sentence with "نظرية", calm certainty for "المؤكد".
- Stress character names and the one surprising word in each sentence. Vary pitch and rhythm; never a flat, even read.
- Natural breaths; a real human performer, not a news anchor and not a robot.
- The final question: warm, smiling, inviting the viewer to answer.
- Read the Arabic transcript exactly as written, every word, nothing added, nothing skipped. Never read these notes.

#### TRANSCRIPT"""
OUTRO_DIRECTION = """# AUDIO PROFILE
The same Saudi storyteller, warm and friendly, white Saudi dialect.

### DIRECTOR'S NOTES
- A quick, friendly call to action, smiling, like recommending something to a friend. Natural, not salesy.
- Read the Arabic transcript exactly as written. Never read these notes.

#### TRANSCRIPT"""
VOICE_NAME = "Charon"  # الصوت الوحيد المعتمد من المالك (20 نوفمبر 2026): لا يُغيَّر
# إيقاع المحترفين (طلب المالك 20 نوفمبر 2026): الصوت كان بطيئاً، لكن التسريع بعد التسجيل يُسمع غير طبيعي (ملاحظة المالك).
# الحل: أداء سريع من التوجيه نفسه + قصّ الوقفات الطويلة (tighten_pauses) دون لمس طبقة الصوت،
# وتسريع خفيف لا تلحظه الأذن (حتى 1.08) فقط إن بقي الصوت أطول من الحد.
VOICE_TEMPO = 1.0
MAX_TEMPO = 1.08


def polish_voice(wav):
    """معالجة استوديو: إزالة الطنين، دفء خفيف، وضوح بالترددات الوسطى العليا، تخفيف الصفير، ضغط، ومستوى مناسب للمنصات."""
    tmp = Path(str(wav) + ".p.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af",
        "highpass=f=80,equalizer=f=160:t=q:w=1:g=2,equalizer=f=400:t=q:w=1.4:g=-2,equalizer=f=3200:t=q:w=1.2:g=3,"
        "deesser=i=0.4,acompressor=threshold=-22dB:ratio=3.5:attack=8:release=180:makeup=2.5,loudnorm=I=-15:TP=-1.5:LRA=8",
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
    # stretch (اختياري لكل لقطة، حتى 2.0): إبطاء لقطة نظيفة قصيرة لتغطي جملتها كاملة (21 نوفمبر 2026)
    st = lambda sg: min(2.0, max(1.0, float(sg.get("stretch", 1.0))))
    # zoom_top (اختياري حتى 1.3): تكبير مثبّت من الأعلى يُسقط سطر ترجمة محروقة أسفل اللقطة (21 نوفمبر 2026)
    def zoom(sg):
        z = min(1.3, max(1.0, float(sg.get("zoom_top", 1.0))))
        return "" if z == 1.0 else f"crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:0,"
    total = sum(float(sg["dur"]) * st(sg) for sg in item["segments"]) or 1.0
    # تتمدد اللقطات أو تنكمش معاً لتطابق طول الصوت (بين 0.7 و1.3)، فتبقى كل لقطة على جملتها
    factor = min(1.3, max(0.7, target / total)) if target else 1.0
    if target and total * factor < target - 0.2:  # لقطات أقل من الصوت = تكرار أول اللقطات في النهاية؛ يجب إضافة لقطات
        print(f"تنبيه: اللقطات {total * factor:.1f}ث أقصر من الصوت {target:.1f}ث؛ ستتكرر البداية. أضف لقطات نظيفة.")
    for i, seg in enumerate(item["segments"]):
        url = seg.get("url") or item["source_url"]
        if url not in cache:
            f = d / f"_src{len(cache)}.mp4"
            fetch_source({"source_url": url}, f); check_quality(f)
            cache[url] = f
        out = d / f"_seg{i}.mp4"
        # لا نخرج عن النافذة المراجَعة أبداً: الإطالة تكون بإبطاء خفيف للّقطة نفسها، والتقصير بقصّها
        dur = float(seg["dur"]) * min(factor, 1.0)
        # تصفير توقيت كل لقطة يمنع اختلال تزامن الكتابة بين المصادر المختلفة
        slow = f"setpts=(PTS-STARTPTS)*{max(factor, 1.0) * st(seg):.3f},"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{float(seg['start']):.2f}", "-t", f"{dur:.2f}",
            "-i", str(cache[url]), "-vf", f"{slow}{zoom(seg)}scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=30",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out)], check=True)
        parts.append(out)
    # دمج بمرشّح concat لا بملف قائمة: نسخة ffmpeg الحديثة على خادم الإنتاج أسقطت لقطة كاملة بطريقة القائمة (21 نوفمبر 2026)
    durs = [media_dur(p) for p in parts]
    print("مدد اللقطات:", ", ".join(f"{x:.2f}" for x in durs), "= المجموع", f"{sum(durs):.2f}")
    montage = d / "source.mp4"
    graph = "".join(f"[{k}:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v{k}];" for k in range(len(parts)))
    graph += "".join(f"[v{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *sum((["-i", str(p)] for p in parts), []),
        "-filter_complex", graph, "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        str(montage)], check=True)
    got = media_dur(montage)
    if got < sum(durs) - 0.3:
        print(f"تنبيه: المونتاج {got:.2f}ث أقصر من مجموع اللقطات {sum(durs):.2f}ث؛ لقطة سقطت")
    for p in [*parts, *cache.values()]:
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
    tempo = min(MAX_TEMPO, max(VOICE_TEMPO, sp / (cap - 0.5)))  # إيقاع المحترفين، وأكثر إن زاد الصوت عن الحد
    dur = sp / tempo + 0.5  # لا يُقطع صوت الخاتمة أبداً حتى لو تجاوز الحد قليلاً
    bg = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30,setsar=1[bg]"
    fg = "scale=1000:-2:force_original_aspect_ratio=decrease[fg]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-i", str(wav),
        "-t", f"{dur:.2f}", "-filter_complex",
        f"[0:v]split[a][b];[a]{bg};[b]{fg};[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v];[1:a]atempo={tempo:.3f}[au]",
        "-map", "[v]", "-map", "[au]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-ar", "44100", "-ac", "1", str(out)], check=True)


# موسيقى خلفية أصلية مولَّدة بالمعادلات (طلب المالك 20 نوفمبر 2026: صوت يشبه المحترفين).
# لا مقطوعات خارجية إطلاقاً، فلا مطالبات حقوق: نغمة غامضة ممتدة مع نبض خافت كدقّات القلب، تخفت تلقائياً تحت الصوت.
MUSIC_BED = ("0.16*(sin(2*PI*110*t)+sin(2*PI*110.35*t)+0.7*sin(2*PI*164.81*t)+0.7*sin(2*PI*165.2*t)"
    "+0.45*sin(2*PI*220*t)+0.3*sin(2*PI*261.63*t+sin(2*PI*0.1*t)))*(0.75+0.25*sin(2*PI*0.07*t))"
    "+0.55*sin(2*PI*52*t)*exp(-9*mod(t,1.2))+0.3*sin(2*PI*52*t)*exp(-11*mod(t-0.28,1.2))*gte(mod(t,1.2),0.28)")


def media_dur(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(p.stdout.strip())


def concat(main_mp4, outro_mp4, out, music=False):
    f = "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]"
    amap = "[a]"
    if music:
        t = media_dur(main_mp4) + media_dur(outro_mp4)
        f += (f";aevalsrc='{MUSIC_BED}':s=44100:d={t:.2f},lowpass=f=900,aecho=0.8:0.7:60|120:0.25|0.15,"
              f"afade=t=in:d=1.2,afade=t=out:st={max(0.0, t - 1.5):.2f}:d=1.5,volume=0.5[m0];"
              "[a]aresample=44100,asplit=2[vo][sc];[m0][sc]sidechaincompress=threshold=0.02:ratio=5:attack=25:release=450[m];"
              "[vo][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[am]")
        amap = "[am]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(main_mp4), "-i", str(outro_mp4),
        "-filter_complex", f, "-map", "[v]", "-map", amap,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", str(out)], check=True)


def wav_dur(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def tighten_pauses(wav):
    """يقصّر كل وقفة أطول من 0.35 ثانية إلى 0.22 دون تغيير سرعة الكلام أو طبقته (أسلوب المونتاج الاحترافي)."""
    tmp = Path(str(wav) + ".t.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af",
        "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=0.35:stop_threshold=-42dB:stop_silence=0.22",
        str(tmp)], check=True)
    tmp.replace(wav)


def fit_wav(src, dst, mx):
    """تسريع خفيف لا تلحظه الأذن (حتى MAX_TEMPO) فقط إن زاد الصوت عن الحد الأقصى بالثواني؛ وإلا يبقى كما هو."""
    dd = wav_dur(src)
    tempo = min(MAX_TEMPO, max(VOICE_TEMPO, dd / mx))
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


# لحظات صوت الأنمي (طلب المالك 20 نوفمبر 2026): يتوقف صوتنا بعد جملة، فتُسمع لحظة قصيرة من الأنمي بصوتها
# (جملة شهيرة، صرخة، ضربة) ثم يكمل الشرح. اختيارية لكل بند عبر `beats`، وحدودها يفحصها seo_check.py:
# لحظتان كحد أقصى، كل واحدة 4.5 ثانية (جملة شهيرة كاملة)، ومجموعها 6 ثوانٍ، ومن مصادر رسمية فقط. لا صوت أنمي خلفيةً طوال المقطع.
def sentence_ends(speech, wav):
    """أزمنة نهايات الجمل في الصوت: موضع تقديري بنسبة الحروف، ثم أقرب وقفة مكتشفة فعلاً."""
    parts = [p for p in re.split(r"(?<=[.؟!?])\s+", speech.strip()) if p]
    total, dur = sum(len(p) for p in parts) or 1, wav_dur(wav)
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav), "-af", "silencedetect=n=-42dB:d=0.12", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    mids = [(x + y) / 2 for x, y in zip(starts, ends)]
    out, acc = [], 0
    for p in parts:
        acc += len(p); est = dur * acc / total
        out.append(min(mids, key=lambda m: abs(m - est)) if mids else est)
    return out


def _norm_cut(src, start, length, dst, beat=False, video_dur=None):
    """يقصّ جزءاً بتنسيق موحّد (1080x1920، 30 إطاراً، صوت أحادي 44.1 كيلوهرتز) ليُدمج بلا اختلال.
    video_dur (للحظات الأنمي): الصورة من أول video_dur ثانية فقط، مُبطّأة لتغطي الجملة كاملة، فلا تظهر لقطة لاحقة لا تخص القصة."""
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,format=yuv420p"
    af = "aresample=44100"
    if beat:  # لحظة الأنمي: الإطار كاملاً فوق خلفية مموّهة (لا تُقصّ ترجمته)، ومستوى قريب من صوتنا مع دخول وخروج ناعمين
        hold = ""
        if video_dur and length and video_dur < length:
            hold = f"trim=0:{video_dur:.3f},setpts=(PTS-STARTPTS)*{length / video_dur:.4f},"
        vf = (f"{hold}split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24,eq=brightness=-0.12[bg];"
              "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30,format=yuv420p")
        af = f"loudnorm=I=-16:TP=-1.5,afade=t=in:d=0.08,afade=t=out:st={max(0.0, length - 0.2):.2f}:d=0.2,aresample=44100"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}"] + (["-t", f"{length:.3f}"] if length else []) + [
        "-i", str(src), "-filter_complex" if beat else "-vf", vf, "-af", af, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ac", "1", str(dst)]
    subprocess.run(cmd, check=True)


def insert_beats(it, d, video, wav):
    beats = sorted(it.get("beats") or [], key=lambda b: int(b["after"]))
    if not beats:
        return
    ends, vdur = sentence_ends(it["speech"], wav), media_dur(video)
    pieces, cur, cache = [], 0.0, {}
    for i, b in enumerate(beats):
        t = min(ends[int(b["after"]) - 1] + 0.05, vdur)
        a = d / f"_bpart{i}.mp4"; _norm_cut(video, cur, t - cur, a); pieces.append(a)
        url = b.get("url") or it["source_url"]
        if url not in cache:
            src = d / f"_bsrc{len(cache)}.mp4"; fetch_source({"source_url": url}, src); check_quality(src)
            if not has_audio(src):
                raise SystemExit(f"لحظة الأنمي بلا صوت: {url}")
            cache[url] = src
        c = d / f"_beat{i}.mp4"; pieces.append(c)
        _norm_cut(cache[url], float(b["start"]), float(b["dur"]), c, beat=True, video_dur=b.get("video_dur") and float(b["video_dur"]))
        cur = t
    tail = d / "_btail.mp4"; _norm_cut(video, cur, None, tail); pieces.append(tail)
    n = len(pieces)
    f = "".join(f"[{k}:v][{k}:a]" for k in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    tmp = d / "_beats_out.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *sum((["-i", str(p)] for p in pieces), []),
        "-filter_complex", f, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "1", str(tmp)], check=True)
    tmp.replace(video)
    for p in [*pieces, *cache.values()]:
        p.unlink()
    print("لحظات الأنمي:", ", ".join(f"بعد الجملة {b['after']} ({b['dur']}ث)" for b in beats))


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
            # طلب المالك 20 نوفمبر 2026: إيقاع المحترفين دائماً، والمقطع الشرحي 25 إلى 35 ثانية بالخاتمة
            tighten_pauses(wav)
            fitted = d / "voice_fit.wav"
            fit_wav(wav, fitted, MAX_MAIN_SECONDS if it.get("format") == "explainer" else 999.0); fitted.replace(wav)
            polish_voice(wav)
        if it.get("segments"):
            src = build_montage(it, d, target=wav_dur(wav) + 1.0)
        else:
            src = d / "source.mp4"; fetch_source(it, src); check_quality(src)
    build_video(src, wav, d / "video.mp4", {**meta, **{k: it[k] for k in ("key", "display_title", "english_title", "accent", "clip_start", "audio_mode", "tail") if k in it},
        **({"clip_start": 0.0} if it.get("segments") else {})}, d, segs)
    if it.get("beats") and not it.get("speech_end"):
        insert_beats(it, d, d / "video.mp4", wav)
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
        concat(d / "video.mp4", d / f"outro-{plat}.mp4", d / f"video-{plat}.mp4",
            music=it.get("format") == "explainer" and it.get("music", True))
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
