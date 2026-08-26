import logging
import sys

# تهيئة إعدادات المراقبة الأساسية
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout) # لطباعة الأحداث مباشرة في شاشة السيرفر
    ]
)

# إنشاء "المراقب" الذي سيسجل لنا الأخبار من داخل السيرفر
system_logger = logging.getLogger("AlqasemyTrader")