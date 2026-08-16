import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_tunis_viral_short as b

# Tight editorial cut: keep the Tunisian Arabic voice natural and leave breathing room for the visual hook/CTA.
b.SCRIPT = (
    "عندك يوم واحد في تونس؟ امشِ معي. "
    "ابدأ من المدينة العتيقة: أزقة، أسواق، وجامع الزيتونة. "
    "اخرج من باب البحر إلى شارع الحبيب بورقيبة. "
    "بعدها اتجه إلى سيدي بوسعيد، أبيض وأزرق فوق البحر. "
    "وقبل الغروب، مرّ على قرطاج. "
    "احفظ الفيديو لرحلتك إلى تونس."
)

# Edge TTS sometimes returns audio without WordBoundary metadata. Keep true metadata when present;
# otherwise derive natural-looking word timings from the measured narration duration instead of
# dropping the kinetic captions entirely.
_original_make_voice = b.make_voice


async def make_voice_with_timing_fallback():
    voice_path, words = await _original_make_voice()
    if words:
        return voice_path, words

    duration = b.probe(voice_path)
    tokens = re.findall(r"\S+", b.SCRIPT)
    weights = []
    for token in tokens:
        letters = len(re.sub(r"[^\w\u0600-\u06FF]", "", token))
        weight = max(0.65, 0.22 * max(letters, 2))
        if token.endswith((".", "؟", "!", "؛")):
            weight += 0.55
        elif token.endswith((",", "،", ":")):
            weight += 0.28
        weights.append(weight)

    start_pad = 0.08
    usable = max(1.0, min(duration - start_pad - 0.08, 27.2))
    scale = usable / sum(weights)
    cursor = start_pad
    derived = []
    for token, weight in zip(tokens, weights):
        slot = weight * scale
        spoken = max(0.18, slot * 0.88)
        derived.append({"text": token, "start": cursor, "end": min(duration, cursor + spoken)})
        cursor += slot
    print(f"Derived {len(derived)} word timings from {duration:.2f}s narration")
    return voice_path, derived


b.make_voice = make_voice_with_timing_fallback

# Patch two FFmpeg compatibility issues while preserving the richer edit:
# 1) split the voice before sidechain ducking because a filter output cannot be consumed twice;
# 2) use a stable top accent bar rather than a drawbox expression that is version-sensitive.
_original_run = b.run


def run_fixed(*args: str):
    patched = list(args)
    if "-filter_complex" in patched:
        i = patched.index("-filter_complex") + 1
        graph = patched[i]
        old = (
            "[1:a]volume=0.22[m];[0:a]volume=1.05[vo];"
            "[m][vo]sidechaincompress=threshold=0.045:ratio=6:attack=12:release=220[duck];"
            "[duck][vo][2:a]amix=inputs=3:duration=longest:normalize=0,alimiter=limit=0.95[a]"
        )
        if graph == old:
            patched[i] = (
                "[1:a]aresample=48000,volume=0.22[m];"
                "[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,volume=1.05,asplit=2[vo_sc][vo_mix];"
                "[m][vo_sc]sidechaincompress=threshold=0.045:ratio=6:attack=12:release=220[duck];"
                "[duck][vo_mix][2:a]amix=inputs=3:duration=longest:normalize=0,alimiter=limit=0.95[a]"
            )
    if "-vf" in patched:
        i = patched.index("-vf") + 1
        patched[i] = patched[i].replace(
            "drawbox=x=0:y=0:w='iw*t/28':h=14:color=0xFFD400@1:t=fill",
            "drawbox=x=0:y=0:w=iw:h=14:color=0xFFD400@1:t=fill",
        )
    return _original_run(*patched)


b.run = run_fixed

if __name__ == "__main__":
    asyncio.run(b.main())
