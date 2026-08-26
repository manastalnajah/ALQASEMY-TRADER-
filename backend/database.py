import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

# 1. إجبار بايثون على تجاهل الذاكرة وقراءة ملف .env الجديد
load_dotenv(override=True)

SQLALCHEMY_DATABASE_URL = os.getenv("SUPABASE_DB_URL")

if not SQLALCHEMY_DATABASE_URL:
    raise ValueError("⚠️ خطأ: لم يتم العثور على رابط قاعدة البيانات في ملف .env")

# سطر لاختبار الرابط (يقوم بإخفاء كلمة المرور للآمان ويطبع الباقي)
safe_url = SQLALCHEMY_DATABASE_URL.replace("Malek4013%23", "*****")
print(f"🔗 جاري محاولة الاتصال بالرابط: {safe_url}")

# 3. إعداد محرك الاتصال
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 4. إعداد مصنع الجلسات
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 5. القالب الأساسي
Base = declarative_base()

# 6. دالة حقن التبعية
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()