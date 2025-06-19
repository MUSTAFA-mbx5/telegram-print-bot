# 1. ابدأ من صورة بايثون رسمية وخفيفة
FROM python:3.9-slim

# 2. حدد مجلد العمل داخل الحاوية
WORKDIR /app

# 3. تحديث وتثبيت مكتبات النظام المطلوبة
# هذه هي بديل أوامر !apt-get التي كانت في كودك الأصلي
RUN apt-get update && apt-get install -y \
    libarchive-dev \
    graphviz \
    libgeos-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    && rm -rf /var/lib/apt/lists/*

# 4. انسخ ملف الاعتماديات إلى داخل الحاوية
COPY requirements.txt .

# 5. ثبت مكتبات بايثون باستخدام pip
RUN pip install --no-cache-dir -r requirements.txt

# 6. انسخ الكود الخاص بالبوت إلى داخل الحاوية
COPY bot.py .

# 7. الأمر الذي سيتم تشغيله عند بدء الحاوية
CMD ["python", "bot.py"]
