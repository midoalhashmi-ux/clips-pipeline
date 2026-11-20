"""«عين» الخط على المقاطع المرشحة (20 نوفمبر 2026): ينزّل كل رابط في scan_jobs.json على خادم الإنتاج،
ويفحص دقته، ويصنع لوحة مصغّرات (لقطة كل ثانية مختومة برقمها) ليختار Claude نوافذ تظهر فيها الشخصية المذكورة.
المخرجات في scans_out/: <name>.jpg و<name>.json (الدقة والمدة والخطأ إن وُجد)."""
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
