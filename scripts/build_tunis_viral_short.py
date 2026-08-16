from __future__ import annotations

import asyncio
import html
import io
import json
import math
import random
import re
import subprocess
import time
import wave
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import requests

OUT = Path("outputs_viral")
WORK = Path("build_tunis_viral")
OUT.mkdir(exist_ok=True)
WORK.mkdir(exist_ok=True)

DURATION = 28.0
FPS = 30
W, H = 1080, 1920
VOICE = "ar-TN-HediNeural"

# Short enough to keep a natural speaking pace; written as a punchy travel-short voiceover.
SCRIPT = (
    "عندك يوم واحد فقط في تونس؟ هذا هو المسار. "
    "ابدأ من المدينة العتيقة، بين الأزقة والأسواق وجامع الزيتونة. "
    "بعدها اخرج من باب البحر وامشِ في شارع الحبيب بورقيبة. "
    "ثم خذ القطار إلى سيدي بوسعيد: أبيض، أزرق، وبحر في كل زاوية. "
    "اختم يومك في قرطاج وقت الغروب. "
    "احفظ الفيديو، لأن هذا البرنامج يعطيك تونس في يوم واحد."
)

SCENES = [
    ("Medina of Tunis Tunisia", 0.0, 3.3, "عندك يوم واحد فقط في تونس؟"),
    ("Medina Tunis souk Tunisia", 3.0, 6.8, "المدينة العتيقة"),
    ("Zitouna Mosque Tunis Tunisia", 6.5, 10.0, "الزيتونة والأسواق"),
    ("Bab el Bhar Tunis Tunisia", 9.7, 13.1, "باب البحر"),
    ("Avenue Habib Bourguiba Tunis Tunisia", 12.8, 16.3, "شارع الحبيب بورقيبة"),
    ("Sidi Bou Said Tunisia blue white sea", 16.0, 21.4, "سيدي بوسعيد"),
    ("Carthage Tunisia ruins sunset", 21.1, 25.2, "قرطاج"),
    ("Tunis Tunisia travel city", 24.9, 28.0, "احفظ هذا المسار"),
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "TunisViralShortBuilder/2.0 (GitHub Actions; contact via repository)",
    "Accept": "*/*",
})


def run(*args: str) -> None:
    print("+", " ".join(args))
    subprocess.run(args, check=True)


def probe(path: Path) -> float:
    p = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ], check=True, capture_output=True, text=True)
    return float(p.stdout.strip())


def strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def clean_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def request_with_backoff(url: str, *, params=None, timeout=45, binary=False):
    last = None
    for attempt in range(6):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
            if r.status_code == 429:
                delay = 2.0 + attempt * 2.5
                print(f"429 from {url}; sleeping {delay:.1f}s")
                time.sleep(delay)
                last = r
                continue
            r.raise_for_status()
            return r.content if binary else r
        except requests.RequestException as exc:
            last = exc
            time.sleep(1.5 + attempt * 1.5)
    if isinstance(last, requests.Response):
        last.raise_for_status()
    raise RuntimeError(f"request failed: {url}: {last}")


def commons_asset(query: str, stem: Path) -> tuple[Path, dict]:
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": 20,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": 1600,
        "format": "json",
    }
    r = request_with_backoff(api, params=params, timeout=30)
    pages = list(r.json().get("query", {}).get("pages", {}).values())
    pages.sort(key=lambda x: x.get("index", 9999))

    for page in pages:
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = info.get("mime", "")
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if mime not in {"image/jpeg", "image/png"} or width < 900 or height < 500:
            continue
        url = clean_url(info.get("thumburl") or info.get("url") or "")
        if not url:
            continue
        ext = ".jpg" if mime == "image/jpeg" else ".png"
        path = stem.with_suffix(ext)
        try:
            data = request_with_backoff(url, timeout=60, binary=True)
        except Exception as exc:
            print("asset download failed; trying next result:", exc)
            continue
        if len(data) < 30000:
            continue
        path.write_bytes(data)
        meta = info.get("extmetadata") or {}
        title = page.get("title", "")
        return path, {
            "query": query,
            "title": title,
            "source": "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_")),
            "license": strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
            "artist": strip_html((meta.get("Artist") or {}).get("value", "")),
        }
    raise RuntimeError(f"No Commons asset for {query}")


async def make_voice() -> tuple[Path, list[dict]]:
    import edge_tts

    out = WORK / "voice.mp3"
    words: list[dict] = []
    audio = bytearray()
    communicate = edge_tts.Communicate(SCRIPT, VOICE, rate="-3%", pitch="+0Hz")
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            # edge-tts reports 100-nanosecond ticks.
            start = float(chunk["offset"]) / 10_000_000.0
            dur = max(0.12, float(chunk.get("duration", 0)) / 10_000_000.0)
            words.append({"text": chunk["text"].strip(), "start": start, "end": start + dur})
    out.write_bytes(bytes(audio))
    dur = probe(out)
    print("Narration duration:", dur)
    # Only a very light correction is allowed. If the copy is too long, fail instead of making chipmunk audio.
    if dur > 28.5:
        raise RuntimeError(f"Narration too long at natural pace: {dur:.2f}s")
    return out, words


def ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def escape_ass(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def make_captions(words: list[dict], path: Path) -> None:
    # Big word-synced captions: each active word pops, with neighbouring words retained for context.
    header = f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Cap,DejaVu Sans,72,&H00FFFFFF,&H000000FF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,5,2,2,80,80,270,1\nStyle: Hook,DejaVu Sans,88,&H00FFFFFF,&H000000FF,&H00101010,&H8A000000,-1,0,0,0,100,100,0,0,3,4,0,8,70,70,120,1\nStyle: Label,DejaVu Sans,54,&H00FFFFFF,&H000000FF,&H00202020,&H85000000,-1,0,0,0,100,100,0,0,3,3,0,8,70,70,110,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    lines = [header]

    # Hook + location labels.
    lines.append(f"Dialogue: 2,{ass_time(0)},{ass_time(2.7)},Hook,,0,0,0,,{{\\fad(80,120)\\fscx108\\fscy108\\t(0,220,\\fscx100\\fscy100)}}عندك يوم واحد في تونس؟\n")
    for _, start, end, label in SCENES[1:]:
        lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(min(end, start+1.15))},Label,,0,0,0,,{{\\fad(80,160)\\fscx112\\fscy112\\t(0,220,\\fscx100\\fscy100)}}{escape_ass(label)}\n")

    # Word-by-word dynamic transcription, grouped in 4-word windows.
    for i, w in enumerate(words):
        if not w["text"]:
            continue
        start = w["start"]
        end = max(w["end"], start + 0.22)
        group_start = max(0, i - 1)
        group_end = min(len(words), i + 3)
        parts = []
        for j in range(group_start, group_end):
            txt = escape_ass(words[j]["text"])
            if j == i:
                parts.append(r"{\c&H00D7FF&\fscx118\fscy118\t(0,130,\fscx100\fscy100)}" + txt + r"{\c&H00FFFFFF&\fscx100\fscy100}")
            else:
                parts.append(txt)
        line = " ".join(parts)
        lines.append(f"Dialogue: 3,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{line}\n")

    # End-card CTA.
    lines.append(f"Dialogue: 4,{ass_time(25.2)},{ass_time(28.0)},Hook,,0,0,0,,{{\\fad(100,180)\\fscx106\\fscy106\\t(0,240,\\fscx100\\fscy100)}}احفظ الفيديو لرحلتك 🇹🇳\n")
    path.write_text("".join(lines), encoding="utf-8")


def make_music(path: Path, seconds: float = DURATION) -> None:
    sr = 48000
    frames = int(sr * seconds)
    rng = random.Random(7)
    bpm = 112.0
    beat = 60.0 / bpm
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        chunk = bytearray()
        for n in range(frames):
            t = n / sr
            # Warm bass pulse + airy pad.
            bass_freq = 55.0 if int(t / (beat * 4)) % 2 == 0 else 65.4
            phase = t % beat
            kick_env = math.exp(-phase * 15.0)
            kick = math.sin(2 * math.pi * (58 + 20 * kick_env) * t) * kick_env * 0.62
            bass = math.sin(2 * math.pi * bass_freq * t) * 0.13
            pad = (math.sin(2 * math.pi * 220 * t) + math.sin(2 * math.pi * 329.6 * t)) * 0.025
            # Hi-hat on eighth notes.
            eighth = beat / 2
            hp = t % eighth
            hat_env = math.exp(-hp * 55.0)
            hat = (rng.random() * 2 - 1) * hat_env * 0.08
            # Clap on 2 and 4.
            beat_idx = int(t / beat) % 4
            clap_phase = t % beat
            clap = 0.0
            if beat_idx in (1, 3):
                clap = (rng.random() * 2 - 1) * math.exp(-clap_phase * 28.0) * 0.11
            x = max(-0.95, min(0.95, kick + bass + pad + hat + clap))
            val = int(x * 32767)
            chunk += int(val).to_bytes(2, "little", signed=True) * 2
            if len(chunk) >= sr * 4:
                wf.writeframesraw(chunk)
                chunk.clear()
        if chunk:
            wf.writeframesraw(chunk)
    path.write_bytes(buf.getvalue())


def make_whoosh(path: Path, seconds: float = DURATION) -> None:
    sr = 48000
    hits = [3.0, 6.5, 9.7, 12.8, 16.0, 21.1, 24.9]
    rng = random.Random(19)
    frames = int(sr * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        chunk = bytearray()
        for n in range(frames):
            t = n / sr
            x = 0.0
            for hit in hits:
                d = t - hit
                if -0.18 <= d <= 0.28:
                    p = (d + 0.18) / 0.46
                    env = math.sin(math.pi * p) ** 2
                    noise = (rng.random() * 2 - 1)
                    # Bright sweep + tiny tonal ping.
                    x += noise * env * 0.15 + math.sin(2 * math.pi * (500 + 1500 * p) * t) * env * 0.035
            val = int(max(-0.9, min(0.9, x)) * 32767)
            chunk += int(val).to_bytes(2, "little", signed=True) * 2
            if len(chunk) >= sr * 4:
                wf.writeframesraw(chunk)
                chunk.clear()
        if chunk:
            wf.writeframesraw(chunk)
    path.write_bytes(buf.getvalue())


def image_clip(src: Path, out: Path, seconds: float, idx: int) -> None:
    frames = int(math.ceil(seconds * FPS))
    # Alternate zoom direction and horizontal push for variety.
    if idx % 2 == 0:
        z = "max(1.16-0.00055*on,1.02)"
        x = "iw/2-(iw/zoom/2)+18*sin(on/16)"
    else:
        z = "min(1.02+0.00055*on,1.16)"
        x = "iw/2-(iw/zoom/2)-18*sin(on/16)"
    vf = (
        f"scale=1500:2400:force_original_aspect_ratio=increase,"
        f"crop=1500:2400,"
        f"zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
        "eq=contrast=1.10:saturation=1.18:brightness=-0.015,"
        "vignette=PI/8,setsar=1"
    )
    run("ffmpeg", "-y", "-loop", "1", "-i", str(src), "-t", f"{seconds:.3f}", "-vf", vf,
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS), str(out))


def build_visual_track(assets: list[Path]) -> Path:
    clips = []
    # Use scene durations including transition overlap.
    for idx, ((_, start, end, _), asset) in enumerate(zip(SCENES, assets)):
        dur = end - start
        clip = WORK / f"scene-{idx+1}.mp4"
        image_clip(asset, clip, dur + 0.35, idx)
        clips.append(clip)

    # xfade chain with overlaps at the requested scene starts.
    inputs = []
    for clip in clips:
        inputs += ["-i", str(clip)]
    filter_parts = []
    current = "[0:v]"
    for i in range(1, len(clips)):
        out = f"[v{i}]"
        offset = SCENES[i][1]
        transition = ["fade", "slideleft", "slideright", "circleopen", "smoothleft", "wipeup", "radial"][i-1]
        filter_parts.append(f"{current}[{i}:v]xfade=transition={transition}:duration=0.35:offset={offset:.2f}{out}")
        current = out
    filt = ";".join(filter_parts)
    out = WORK / "visual.mp4"
    run("ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", current,
        "-t", f"{DURATION:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(FPS), str(out))
    return out


async def main() -> None:
    voice, words = await make_voice()
    print("Word boundaries:", len(words))

    assets = []
    credits = []
    for idx, (query, *_rest) in enumerate(SCENES, start=1):
        try:
            asset, credit = commons_asset(query, WORK / f"asset-{idx}")
        except Exception as exc:
            print("Primary query failed; fallback to Tunis Tunisia:", exc)
            asset, credit = commons_asset("Tunis Tunisia", WORK / f"asset-{idx}")
        assets.append(asset)
        credit["scene"] = idx
        credits.append(credit)
        time.sleep(1.4)

    visual = build_visual_track(assets)
    ass = WORK / "captions.ass"
    make_captions(words, ass)

    music = WORK / "music.wav"
    whoosh = WORK / "whoosh.wav"
    make_music(music)
    make_whoosh(whoosh)

    # Mix voice, music, and transition SFX. Duck the music during narration with sidechaincompress.
    audio_mix = WORK / "mix.m4a"
    run(
        "ffmpeg", "-y", "-i", str(voice), "-i", str(music), "-i", str(whoosh),
        "-filter_complex",
        "[1:a]volume=0.22[m];[0:a]volume=1.05[vo];[m][vo]sidechaincompress=threshold=0.045:ratio=6:attack=12:release=220[duck];[duck][vo][2:a]amix=inputs=3:duration=longest:normalize=0,alimiter=limit=0.95[a]",
        "-map", "[a]", "-t", f"{DURATION:.2f}", "-c:a", "aac", "-b:a", "192k", str(audio_mix)
    )

    final = OUT / "tunis-one-day-ar-viral-28s.mp4"
    vf = (
        f"subtitles={ass}:fontsdir=/usr/share/fonts/truetype/dejavu,"
        "drawbox=x=0:y=0:w=iw:h=14:color=white@0.95:t=fill,"
        "drawbox=x=0:y=0:w='iw*t/28':h=14:color=0xFFD400@1:t=fill"
    )
    run(
        "ffmpeg", "-y", "-i", str(visual), "-i", str(audio_mix),
        "-vf", vf, "-map", "0:v", "-map", "1:a", "-t", f"{DURATION:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)
    )

    (OUT / "credits.json").write_text(json.dumps(credits, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "script.txt").write_text(SCRIPT, encoding="utf-8")
    summary = {
        "file": final.name,
        "duration": probe(final),
        "resolution": f"{W}x{H}",
        "fps": FPS,
        "voice": VOICE,
        "word_boundaries": len(words),
        "features": [
            "natural-speed Arabic narration",
            "word-synced kinetic captions",
            "8 fast visual beats",
            "xfade transitions",
            "animated hook/location labels",
            "custom beat + whoosh SFX",
            "music ducking under voice",
            "progress bar + end-card CTA",
        ],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
