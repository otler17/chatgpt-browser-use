from __future__ import annotations

import asyncio
import html
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

import requests

OUT = Path("outputs")
WORK = Path("build_tunis")
OUT.mkdir(exist_ok=True)
WORK.mkdir(exist_ok=True)

VIDEOS = [
    {
        "id": "01-medina-tunis",
        "title": "تونس العتيقة: قلب العاصمة",
        "segments": [
            "اكتشف تونس من قلب المدينة العتيقة، حيث تبدأ الحكاية بين الأزقة القديمة.",
            "مرّ بجامع الزيتونة، ثم تجوّل في الأسواق المليئة بالعطور والنحاس والحرف التقليدية.",
            "عند باب البحر، تنتقل من سحر التاريخ إلى إيقاع المدينة الحديثة.",
            "واصل جولتك في شارع الحبيب بورقيبة واستمتع بالمقاهي والعمارة وروح العاصمة.",
            "تونس تجمع في خطوات قليلة بين التراث والحياة اليومية والضيافة الدافئة.",
            "ضع المدينة العتيقة في أول برنامجك، واترك وقتاً لتتوه في تفاصيلها الجميلة.",
        ],
        "queries": [
            "Medina of Tunis Tunisia",
            "Zitouna Mosque Tunis Tunisia",
            "Souk Medina Tunis Tunisia",
            "Bab el Bhar Tunis Tunisia",
            "Avenue Habib Bourguiba Tunis Tunisia",
            "Tunis old city Tunisia",
        ],
    },
    {
        "id": "02-sidi-bou-said-carthage",
        "title": "سيدي بوسعيد وقرطاج: الأزرق والتاريخ",
        "segments": [
            "في دقائق من وسط تونس، تصل إلى سيدي بوسعيد بأبوابه الزرقاء وبيوته البيضاء.",
            "اصعد الأزقة المطلة على البحر، وخذ وقتك مع القهوة والمناظر الهادئة.",
            "بعدها اتجه إلى قرطاج، حيث تنتشر الآثار فوق تلال تطل على خليج تونس.",
            "بين الحمامات الأنطونية والمواقع القديمة، تشعر بقرب البحر وعمق التاريخ.",
            "هذه الجولة تجمع اللون الأزرق، والآثار، والهواء البحري في يوم واحد.",
            "إن كنت تحب التصوير والتاريخ، فاجعل سيدي بوسعيد وقرطاج معاً في برنامجك.",
        ],
        "queries": [
            "Sidi Bou Said Tunisia blue white",
            "Sidi Bou Said Tunisia sea",
            "Carthage Tunisia ruins",
            "Antonine Baths Carthage Tunisia",
            "Gulf of Tunis Sidi Bou Said",
            "Carthage Tunisia archaeological site",
        ],
    },
    {
        "id": "03-tunis-taste-culture",
        "title": "تونس: ثقافة ونكهات وحياة محلية",
        "segments": [
            "لتعيش تونس بطعمها الحقيقي، ابدأ صباحك في العاصمة ثم اتجه إلى متحف باردو.",
            "بعد الفن والتاريخ، ارجع إلى المدينة لتجرب البريك وأطباقاً تونسية بنكهة حارة.",
            "توقف في مقهى شعبي، واطلب الشاي أو القهوة على مهل.",
            "في الأسواق، ستجد التوابل والحلويات والهدايا والحرف التي تحمل روح تونس.",
            "ومع المساء، تصبح شوارع العاصمة مكاناً جميلاً للمشي واكتشاف الحياة المحلية.",
            "رحلة تونس ليست مشاهدة فقط؛ إنها أصوات وروائح ونكهات وذكريات تعود بها معك.",
        ],
        "queries": [
            "Bardo National Museum Tunisia",
            "Tunisian brik food Tunisia",
            "Tunis cafe Tunisia",
            "Tunis spices market Tunisia",
            "Avenue Habib Bourguiba Tunis evening",
            "Tunis Medina market Tunisia",
        ],
    },
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "TunisTourismVideoBuilder/1.0 (GitHub Actions)"})


def run(*args: str) -> None:
    print("+", " ".join(args))
    subprocess.run(args, check=True)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    return html.unescape(value).strip()


def commons_image(query: str, target_stem: Path) -> tuple[Path, dict]:
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": 15,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "format": "json",
    }
    response = SESSION.get(api, params=params, timeout=30)
    response.raise_for_status()
    pages = list(response.json().get("query", {}).get("pages", {}).values())
    pages.sort(key=lambda p: p.get("index", 9999))

    for page in pages:
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = info.get("mime", "")
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if mime not in {"image/jpeg", "image/png"} or width < 800 or height < 500:
            continue
        url = info.get("url")
        if not url:
            continue
        suffix = ".jpg" if mime == "image/jpeg" else ".png"
        path = target_stem.with_suffix(suffix)
        img = SESSION.get(url, timeout=60)
        img.raise_for_status()
        if len(img.content) < 20000:
            continue
        path.write_bytes(img.content)
        meta = info.get("extmetadata") or {}
        title = page.get("title", "")
        credits = {
            "query": query,
            "title": title,
            "source": "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_")),
            "license": strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
            "license_url": strip_html((meta.get("LicenseUrl") or {}).get("value", "")),
            "artist": strip_html((meta.get("Artist") or {}).get("value", "")),
            "credit": strip_html((meta.get("Credit") or {}).get("value", "")),
        }
        return path, credits

    if query != "Tunis Tunisia":
        return commons_image("Tunis Tunisia", target_stem)
    raise RuntimeError(f"No suitable Wikimedia Commons image found for: {query}")


def make_ass(path: Path, segments: list[str]) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,DejaVu Sans,62,&H00FFFFFF,&H000000FF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,1,4,1,2,70,70,150,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = [header]
    for i, text in enumerate(segments):
        start = i * 5
        end = (i + 1) * 5
        lines.append(
            f"Dialogue: 0,0:00:{start:02d}.00,0:00:{end:02d}.00,Default,,0,0,0,,{text}\n"
        )
    path.write_text("".join(lines), encoding="utf-8")


async def edge_segment(text: str, out_path: Path, voice: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=voice, rate="+8%")
    await communicate.save(str(out_path))


async def choose_voice() -> str:
    import edge_tts

    voices = await edge_tts.list_voices()
    for locale in ("ar-TN", "ar-SA", "ar-EG"):
        for voice in voices:
            if voice.get("Locale") == locale:
                print("Using voice:", voice["ShortName"])
                return voice["ShortName"]
    raise RuntimeError("No Arabic Edge TTS voice is available")


def atempo_chain(factor: float) -> str:
    parts = []
    while factor > 2.0:
        parts.append("atempo=2.0")
        factor /= 2.0
    while factor < 0.5:
        parts.append("atempo=0.5")
        factor /= 0.5
    parts.append(f"atempo={factor:.6f}")
    return ",".join(parts)


async def make_segment_audio(text: str, path: Path, voice: str) -> None:
    raw = path.with_suffix(".raw.mp3")
    try:
        await edge_segment(text, raw, voice)
    except Exception as exc:
        print("Edge TTS failed, falling back to gTTS:", exc)
        from gtts import gTTS

        gTTS(text=text, lang="ar").save(str(raw))

    duration = probe_duration(raw)
    filters = []
    if duration > 4.65:
        filters.append(atempo_chain(duration / 4.65))
    filters.extend(["apad=pad_dur=5", "atrim=duration=5", "aresample=48000"])
    run(
        "ffmpeg",
        "-y",
        "-i",
        str(raw),
        "-af",
        ",".join(filters),
        "-ac",
        "2",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        str(path),
    )


async def build() -> None:
    voice = await choose_voice()
    credits_all: list[dict] = []
    scripts_dump: list[dict] = []

    for item in VIDEOS:
        vid_dir = WORK / item["id"]
        vid_dir.mkdir(parents=True, exist_ok=True)
        image_clips: list[Path] = []
        audio_clips: list[Path] = []

        for index, (query, segment) in enumerate(zip(item["queries"], item["segments"]), start=1):
            image_path, credits = commons_image(query, vid_dir / f"image-{index}")
            credits.update({"video": item["id"], "slot": index})
            credits_all.append(credits)

            clip = vid_dir / f"clip-{index}.mp4"
            vf = (
                "scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,"
                "zoompan=z='min(zoom+0.00045,1.055)':d=150:s=1080x1920:fps=30,"
                "setsar=1"
            )
            run(
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image_path),
                "-t",
                "5",
                "-vf",
                vf,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                str(clip),
            )
            image_clips.append(clip)

            audio = vid_dir / f"audio-{index}.wav"
            await make_segment_audio(segment, audio, voice)
            audio_clips.append(audio)

        video_list = vid_dir / "video-list.txt"
        video_list.write_text("".join(f"file '{p.resolve()}'\n" for p in image_clips), encoding="utf-8")
        silent_video = vid_dir / "silent.mp4"
        run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(video_list), "-c", "copy", str(silent_video))

        audio_list = vid_dir / "audio-list.txt"
        audio_list.write_text("".join(f"file '{p.resolve()}'\n" for p in audio_clips), encoding="utf-8")
        narration = vid_dir / "narration.wav"
        run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(audio_list), "-c:a", "pcm_s16le", str(narration))

        ass = vid_dir / "captions.ass"
        make_ass(ass, item["segments"])

        final = OUT / f"{item['id']}-ar-30s.mp4"
        subtitle_filter = f"subtitles={ass}:fontsdir=/usr/share/fonts/truetype/dejavu"
        run(
            "ffmpeg",
            "-y",
            "-i",
            str(silent_video),
            "-i",
            str(narration),
            "-vf",
            subtitle_filter,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-t",
            "30",
            "-movflags",
            "+faststart",
            str(final),
        )
        duration = probe_duration(final)
        if not (29.8 <= duration <= 30.2):
            raise RuntimeError(f"Unexpected duration for {final}: {duration}")
        scripts_dump.append(
            {
                "id": item["id"],
                "title": item["title"],
                "voice": voice,
                "duration": duration,
                "segments": item["segments"],
            }
        )

    (OUT / "credits.json").write_text(
        json.dumps(credits_all, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "scripts.json").write_text(
        json.dumps(scripts_dump, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(build())
