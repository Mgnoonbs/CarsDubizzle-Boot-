import os
import re
import sqlite3
import time
import requests
from bs4 import BeautifulSoup

# --- إعدادات البوت من متغيرات البيئة (GitHub Secrets) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

DB_FILE = "sent_ads.db"


def send_telegram_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        response = requests.post(url, data=payload, timeout=15)
        return response.status_code == 200
    except Exception as e:
        print(f"خطأ في إرسال تليجرام: {e}")
        return False


# --- إدارة قاعدة البيانات ---
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("DROP TABLE IF EXISTS sent_ads")
cursor.execute("""
    CREATE TABLE sent_ads (
        ad_id TEXT PRIMARY KEY
    )
""")
conn.commit()


def mark_sent(ad_id):
    cursor.execute("INSERT OR IGNORE INTO sent_ads (ad_id) VALUES (?)", (str(ad_id),))
    conn.commit()


def fetch_dubizzle_ads():
    target_url = "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?sorting=date_desc&seller_type=OW"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ar-AE,ar;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://uae.dubizzle.com/",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1"
    }

    session = requests.Session()
    ads_list = []

    try:
        print(f"جاري جلب البيانات من: {target_url}")
        res = session.get(target_url, headers=headers, timeout=25)
        print(f"كود الاستجابة: {res.status_code}")

        if res.status_code != 200:
            print("لم نتمكن من الوصول للموقع بشكل مباشر، جاري محاولة الفحص العميق...")

        soup = BeautifulSoup(res.text, "html.parser")
        links = soup.find_all("a", href=True)

        seen_links = set()
        for a in links:
            href = a["href"]
            if "/motors/used-cars/" in href:
                if href.startswith("/"):
                    href = f"https://uae.dubizzle.com{href}"

                clean_link = href.split("?")[0].rstrip("/")
                parts = [p for p in clean_link.split("/") if p]

                # فلترة المعرفات والروابط المباشرة للإعلانات فقط
                if len(parts) >= 6 and parts[-1] not in ["used-cars", "toyota", "motors", "ar", "owner"]:
                    if clean_link in seen_links:
                        continue
                    seen_links.add(clean_link)

                    ad_id = parts[-1]
                    title_text = a.get_text(strip=True)
                    
                    if not title_text or len(title_text) < 3:
                        model_name = parts[-2] if len(parts) >= 2 else "Toyota"
                        title_text = f"Toyota {model_name.replace('-', ' ').title()}"

                    ads_list.append({
                        "id": ad_id,
                        "title": title_text,
                        "link": clean_link
                    })

                    if len(ads_list) >= 5:
                        break

    except Exception as e:
        print(f"خطأ أثناء جلب البيانات: {e}")

    return ads_list


def process_and_send():
    print("بدء العملية...")
    ads = fetch_dubizzle_ads()
    print(f"تم العثور على {len(ads)} إعلانات.")

    if not ads:
        # إذا تعذر السحب المباشر بسبب حظر IP سيرفرات GitHub، يرسل إشعاراً توضيحياً
        print("تعذر جلب البيانات بسبب جدار حماية الموزع (Cloudflare).")
        send_telegram_message(
            CHAT_ID, 
            "⚠️ تنبيه: تم كشف السكربت بواسطة حماية Cloudflare الخاصة بموقع دوبيزل من خوادم GitHub Actions."
        )
        return

    for ad in ads:
        caption = (
            f"🚘 *إعلان سيارة جديد من المالك (Toyota)*\n\n"
            f"🚗 *{ad['title']}*\n"
            f"📍 الموقع: الإمارات\n\n"
            f"🔗 [اضغط هنا لرؤية تفاصيل الإعلان]({ad['link']})"
        )

        if send_telegram_message(CHAT_ID, caption):
            mark_sent(ad["id"])
            print(f"تم الإرسال بنجاح: {ad['title']}")
            time.sleep(2)


if __name__ == "__main__":
    process_and_send()