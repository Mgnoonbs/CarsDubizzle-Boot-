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


def is_already_sent(ad_id):
    cursor.execute("SELECT 1 FROM sent_ads WHERE ad_id = ?", (str(ad_id),))
    return cursor.fetchone() is not None


def mark_sent(ad_id):
    cursor.execute("INSERT OR IGNORE INTO sent_ads (ad_id) VALUES (?)", (str(ad_id),))
    conn.commit()


def fetch_dubizzle_ads():
    # رابط البحث المباشر لسيارات تويوتا مستعملة من المالك مرتبة من الأحدث إلى الأقدم
    target_url = "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?sorting=date_desc&seller_type=OW"
    
    if SCRAPER_API_KEY:
        print("جاري الاتصال عبر ScraperAPI...")
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true"
    else:
        proxy_url = target_url

    ads_list = []

    try:
        res = requests.get(proxy_url, timeout=60)
        print(f"حالة الاستجابة: {res.status_code}")

        if res.status_code != 200:
            print(f"فشل جلب الصفحة: {res.status_code}")
            return []

        soup = BeautifulSoup(res.text, "html.parser")
        
        # البحث عن كافة بطاقات الإعلانات بناءً على data-testid التي تحتوي على listing-
        listing_anchors = soup.find_all("a", attrs={"data-testid": lambda val: val and val.startswith("listing-")})

        # إذا لم يجد عبر data-testid، يبحث عن الروابط المباشرة للإعلانات داخل قائمة الإعلانات
        if not listing_anchors:
            listing_anchors = soup.select("div#listing-card-wrapper a[href*='/motors/used-cars/toyota/']")

        seen_links = set()

        for a in listing_anchors:
            href = a.get("href", "")
            if not href or href in seen_links:
                continue

            seen_links.add(href)
            
            # استخراج معرف الإعلان (ID) من نهاية الرابط
            clean_link = href.split("?")[0].rstrip("/")
            parts = [p for p in clean_link.split("/") if p]
            ad_id = parts[-1] if parts else str(hash(href))

            # استخراج السعر
            price_elem = a.find(attrs={"data-testid": "listing-price"})
            price = price_elem.text.strip() if price_elem else "غير معلن"

            # استخراج اسم وعنوان السيارة
            subheading = a.find(attrs={"data-testid": "subheading-text"})
            if subheading:
                title = subheading.text.strip()
            else:
                headings = a.find_all(attrs={"data-testid": lambda v: v and v.startswith("heading-text-")})
                title = " ".join([h.text.strip() for h in headings]) if headings else "تويوتا مستعملة"

            # استخراج السنة والكيلومترات والموقع
            year_elem = a.find(attrs={"data-testid": "listing-year"})
            year = year_elem.text.strip() if year_elem else "غير محدد"

            km_elem = a.find(attrs={"data-testid": "listing-kilometers"})
            km = km_elem.text.strip() if km_elem else "غير محدد"

            loc_elem = a.find(attrs={"data-testid": "listing-location"})
            location = loc_elem.text.strip() if loc_elem else "الإمارات"

            full_url = href if href.startswith("http") else f"https://uae.dubizzle.com{href}"

            ads_list.append({
                "id": ad_id,
                "title": title,
                "price": price,
                "year": year,
                "km": km,
                "location": location,
                "link": full_url
            })

            if len(ads_list) >= 5:
                break

    except Exception as e:
        print(f"خطأ أثناء تحليل البيانات: {e}")

    return ads_list


def process_and_send():
    print("بدء جلب ومعالجة الإعلانات...")
    ads = fetch_dubizzle_ads()
    print(f"تم العثور على {len(ads)} إعلان تويوتا حقيقي.")

    if not ads:
        print("لم يتم العثور على إعلانات جديدة مطابقة للفلتر.")
        return

    for ad in ads:
        if is_already_sent(ad["id"]):
            print(f"الإعلان {ad['id']} تم إرساله سابقاً.")
            continue

        caption = (
            f"🚘 *إعلان تويوتا جديد (من المالك مباشرة)*\n\n"
            f"🚗 *السيارة:* {ad['title']}\n"
            f"💰 *السعر:* {ad['price']} درهم\n"
            f"📅 *الموديل:* {ad['year']}\n"
            f"🛣️ *الممشى:* {ad['km']}\n"
            f"📍 *الموقع:* {ad['location']}\n\n"
            f"🔗 [اضغط هنا لمشاهدة تفاصيل الإعلان]({ad['link']})"
        )

        if send_telegram_message(CHAT_ID, caption):
            mark_sent(ad["id"])
            print(f"تم الإرسال بنجاح: {ad['title']}")
            time.sleep(2)


if __name__ == "__main__":
    process_and_send()