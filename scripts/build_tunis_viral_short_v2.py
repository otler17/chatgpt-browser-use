import asyncio
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

if __name__ == "__main__":
    asyncio.run(b.main())
