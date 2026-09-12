import os
import sqlite3
import time
import requests
from bs4 import BeautifulSoup

# --- إعدادات البوت والخدمات من متغيرات البيئة ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")

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
    # الرابط الدقيق المفلتر: تويوتا - من المالك - الأحدث أولاً
    target_url = "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?sorting=date_desc&seller_type=OW"
    
    if SCRAPER_API_KEY:
        print("جاري جلب البيانات عبر ScraperAPI مع تفعيل Render...")
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true"
    else:
        proxy_url = target_url

    ads_list = []

    try:
        res = requests.get(proxy_url, timeout=60)
        if res.status_code != 200:
            print(f"فشل جلب الصفحة: {res.status_code}")
            return []

        soup = BeautifulSoup(res.text, "html.parser")
        
        # البحث عن العناصر الخاصة بالإعلانات
        cards = soup.find_all("div", attrs={"data-testid": "listing-card"})
        if not cards:
            cards = soup.find_all(["div", "article"], class_=lambda c: c and "Card" in c if c else False)

        seen_links = set()
        for card in cards:
            try:
                a_tag = card.find("a", href=True)
                if not a_tag:
                    continue

                href = a_tag["href"]
                
                # التأكد الصارم أن الإعلان لسيارة تويوتا
                if "/motors/used-cars/toyota/" not in href:
                    continue

                if href.startswith("/"):
                    href = f"https://uae.dubizzle.com{href}"

                clean_link = href.split("?")[0].rstrip("/")
                parts = [p for p in clean_link.split("/") if p]

                # استبعاد الروابط غير المباشرة
                if len(parts) < 6 or parts[-1] in ["used-cars", "toyota", "motors", "ar", "owner"]:
                    continue

                if clean_link in seen_links:
                    continue
                seen_links.add(clean_link)

                ad_id = parts[-1]

                # استخراج نصوص البطاقة
                lines = [l.strip() for l in card.get_text(separator="\n", strip=True).split("\n") if l.strip()]
                
                # استخراج العنوان (البحث عن أسطر تحتوي تفاصيل الموديل)
                title = ""
                for line in lines:
                    if any(kw in line.lower() for kw in ["تويوتا", "toyota", "كامري", "كورولا", "لاندكروزر", "برادو", "ياريس", "هايلكس", "فورشنر", "اف جي"]):
                        title = line
                        break

                if not title and len(lines) > 0:
                    title = lines[0]

                if not title or title.isdigit():
                    model_name = parts[-2] if len(parts) >= 2 else "Toyota"
                    title = f"تويوتا {model_name.replace('-', ' ').title()}"

                # استخراج السعر
                price = "غير محدد"
                for line in lines:
                    if "درهم" in line or "AED" in line:
                        price = line
                        break

                ads_list.append({
                    "id": ad_id,
                    "title": title,
                    "price": price,
                    "link": clean_link
                })

                if len(ads_list) >= 5:
                    break

            except Exception:
                continue

    except Exception as e:
        print(f"خطأ أثناء جلب البيانات: {e}")

    return ads_list


def process_and_send():
    print("بدء عملية التصفح والإرسال...")
    ads = fetch_dubizzle_ads()
    print(f"إجمالي الإعلانات المطابقة للفلتر: {len(ads)}")

    if not ads:
        send_telegram_message(CHAT_ID, "⚠️ لم يتم العثور على إعلانات تويوتا جديدة من المالك حالياً.")
        return

    for ad in ads:
        caption = (
            f"🚘 *إعلان تويوتا جديد (من المالك مباشرة)*\n\n"
            f"🚗 *الموديل:* {ad['title']}\n"
            f"💰 *السعر:* {ad['price']}\n"
            f"📍 *الموقع:* الإمارات\n\n"
            f"🔗 [اضغط هنا لمشاهدة الإعلان على دوبيزل]({ad['link']})"
        )

        if send_telegram_message(CHAT_ID, caption):
            mark_sent(ad["id"])
            print(f"تم الإرسال بنجاح: {ad['title']}")
            time.sleep(2)


if __name__ == "__main__":
    process_and_send()