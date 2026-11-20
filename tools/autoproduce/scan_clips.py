"""«عين» الخط على المقاطع المرشحة (20 نوفمبر 2026): ينزّل كل رابط في scan_jobs.json على خادم الإنتاج،
ويفحص دقته، ويصنع لوحة مصغّرات (لقطة كل ثانية مختومة برقمها) ليختار Claude نوافذ تظهر فيها الشخصية المذكورة.
المخرجات في scans_out/: <name>.jpg و<name>.json (الدقة والمدة والخطأ إن وُجد)، و<name>_audio.txt مع "audio": true."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = Path("scans_out"); OUT.mkdir(exist_ok=True)
FONT = ROOT / "fonts" / "Cairo-Variable.ttf"
sys.path.insert(0, str(ROOT))


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                        "-of", "json", str(p)], capture_output=True, text=True)
    d = json.loads(r.stdout or "{}")
    s = (d.get("streams") or [{}])[0]
    return s.get("width", 0), s.get("height", 0), float((d.get("format") or {}).get("duration", 0) or 0)


def audio_report(src, name):
    """أذن الخط (طلب المالك 20 نوفمبر 2026، لحظات صوت الأنمي): مستوى الصوت كل نصف ثانية، ونص الكلام بتوقيته
    (faster-whisper إن توفّر)، ليختار Claude لحظة قصيرة تطابق الجملة (اسم تقنية، صرخة، ضربة) دون أن يسمع."""
    lines = [f"# {name}: مستوى الصوت كل 0.5 ثانية (dB) — الأعلى = ضربة أو صرخة"]
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-vn", "-af",
        "aresample=16000,asetnsamples=n=8000,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
        "-f", "null", "-"], capture_output=True, text=True).stdout
    t = None
    for ln in log.splitlines():
        if "pts_time:" in ln:
            t = float(ln.split("pts_time:")[1].split()[0])
        elif "RMS_level=" in ln and t is not None:
            v = ln.split("=")[1]
            lines.append(f"{t:6.1f}  {'-inf' if 'inf' in v else f'{float(v):.0f}'}")
    try:
        from faster_whisper import WhisperModel
        lines.append("\n# الكلام بتوقيته (بداية-نهاية بالثواني)")
        import numpy as np  # نقرأ الصوت بـ ffmpeg مباشرة، فلا نعتمد على مكتبة av (اختلاف إصداراتها أفشل القراءة)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
            capture_output=True, check=True).stdout
        audio = np.frombuffer(raw, dtype=np.float32)
        segs, info = WhisperModel("small", device="cpu", compute_type="int8").transcribe(audio, vad_filter=True)
        lines.append(f"# اللغة: {info.language}")
        lines += [f"{sg.start:6.1f}-{sg.end:6.1f}  {sg.text.strip()}" for sg in segs]
    except Exception as e:
        lines.append(f"\n# تعذّر نص الكلام: {str(e)[:150]}")
    (OUT / f"{name}_audio.txt").write_text("\n".join(lines), encoding="utf-8")


def scan(job):
    name, url = job["name"], job["url"]
    src = OUT / f"_{name}.mp4"
    meta = {"name": name, "url": url}
    try:
        if "theplatform.com" in url or url.lower().endswith(".mp4"):
            import produce
            produce.fetch_source({"source_url": url}, src)
        else:
            subprocess.run(["yt-dlp", "-q", "-f", "bv*[height>=1080]+ba/bv*[height>=720]+ba/b[height>=720]/b",
                            "--merge-output-format", "mp4", "-o", str(src), url], check=True, timeout=240)
        w, h, dur = probe(src)
        meta.update({"width": w, "height": h, "duration": round(dur, 1), "quality_ok": min(w, h) >= 720})
        if job.get("times"):  # لحظات محددة بدقة أعلى للتحقق قبل اختيار النوافذ
            frames = []
            for k, t in enumerate(job["times"]):
                f = OUT / f"_{name}_{k:02d}.png"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(src), "-frames:v", "1", "-vf",
                    f"scale=-2:{300 if h > w else 220},drawtext=fontfile={FONT}:text='{t}':x=6:y=6:fontsize=26:fontcolor=yellow:box=1:boxcolor=black@0.6",
                    str(f)], check=True)
                frames.append(f)
            cols = 6
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-pattern_type", "glob", "-i", str(OUT / f"_{name}_*.png"),
                "-vf", f"tile={cols}x{-(-len(frames) // cols)}", "-frames:v", "1", "-q:v", "5", str(OUT / f"{name}_times.jpg")], check=True)
            for f in frames:
                f.unlink()
        step = 1 if dur <= 80 else 2
        n = int(dur // step) + 1
        cols = 10 if h > w else 8
        rows = -(-n // cols)
        vf = (f"fps=1/{step},scale=-2:{180 if h > w else 120},"
              f"drawtext=fontfile={FONT}:text='%{{eif\\:n*{step}\\:d}}':x=6:y=6:fontsize=26:fontcolor=yellow:box=1:boxcolor=black@0.6,"
              f"tile={cols}x{rows}")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-frames:v", "1", "-q:v", "6",
                        str(OUT / f"{name}.jpg")], check=True)
        meta["seconds_per_tile"] = step
        if job.get("audio"):
            audio_report(src, name)
    except Exception as e:
        meta["error"] = str(e)[:300]
    finally:
        src.unlink(missing_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(name, meta.get("width"), meta.get("height"), meta.get("duration"), meta.get("error", ""))


if __name__ == "__main__":
    jobs = json.loads((ROOT / "scan_jobs.json").read_text(encoding="utf-8"))
    for j in jobs:
        scan(j)
