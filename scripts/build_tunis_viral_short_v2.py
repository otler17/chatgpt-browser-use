import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_tunis_viral_short as b

# Shorter editorial cut so the Tunisian Arabic voice stays natural rather than being time-compressed.
b.SCRIPT = (
    "عندك يوم واحد في تونس؟ هذا المسار يكفيك. "
    "ابدأ من المدينة العتيقة: أزقة، أسواق، وجامع الزيتونة. "
    "اخرج من باب البحر وامشِ في شارع الحبيب بورقيبة. "
    "بعدها اتجه إلى سيدي بوسعيد، الأبيض والأزرق فوق البحر، وخذ قهوة على مهل. "
    "وقبل الغروب، مرّ على آثار قرطاج. "
    "احفظ الفيديو؛ هذا برنامج يوم كامل في تونس."
)

if __name__ == "__main__":
    asyncio.run(b.main())
