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


def send_telegram_photo(chat_id, photo_url, caption):
    """إرسال صورة مع النص المصاحب عبر تليجرام"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, data=payload, timeout=20)
        
        # في حال فشل إرسال الصورة (مثل صلاحية الرابط)، يتم الإرسال كرسالة نصية كبديل
        if response.status_code != 200:
            print(f"فشل إرسال الصورة، جاري الإرسال كنص فقط... ({response.text})")
            return send_telegram_message(chat_id, caption)
            
        return True
    except Exception as e:
        print(f"خطأ أثناء إرسال الصورة: {e}")
        return send_telegram_message(chat_id, caption)


def send_telegram_message(chat_id, text):
    """إرسال رسالة نصية فقط"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }
        response = requests.post(url, data=payload, timeout=15)
        return response.status_code == 200
    except Exception as e:
        print(f"خطأ في إرسال تليجرام: {e}")
        return False


# --- إدارة قاعدة البيانات ---
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# إنشاء الجدول فقط إذا لم يكن موجوداً من قبل دون حذف البيانات القديمة
cursor.execute("""
    CREATE TABLE IF NOT EXISTS sent_ads (
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
    target_url = "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?sorting=date_desc&seller_type=OW"
    
    if SCRAPER_API_KEY:
        print("جاري الاتصال عبر ScraperAPI...")
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true&keep_headers=true"
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
        
        listing_anchors = soup.find_all("a", attrs={"data-testid": lambda val: val and val.startswith("listing-")})

        if not listing_anchors:
            listing_anchors = soup.select("div#listing-card-wrapper a[href*='/motors/used-cars/toyota/']")

        seen_links = set()

        for a in listing_anchors:
            href = a.get("href", "")
            if not href or href in seen_links:
                continue

            seen_links.add(href)
            
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

            # استخراج صورة السيارة الحقيقية من داخل معرض الصور المخصص
            image_url = None
            gallery_div = a.find(attrs={"data-testid": "image-gallery"})
            if gallery_div:
                img_tag = gallery_div.find("img", src=lambda s: s and "dbz-images.dubizzle.com" in s)
                if img_tag:
                    image_url = img_tag.get("src")

            # fallback في حال عدم العثور عليها داخل image-gallery
            if not image_url:
                img_tag = a.find("img", src=lambda s: s and "dbz-images.dubizzle.com" in s)
                if img_tag:
                    image_url = img_tag.get("src")

            full_url = href if href.startswith("http") else f"https://uae.dubizzle.com{href}"

            ads_list.append({
                "id": ad_id,
                "title": title,
                "price": price,
                "year": year,
                "km": km,
                "location": location,
                "image": image_url,
                "link": full_url
            })
            if len(ads_list) >= 15:
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

        sent_success = False
        if ad["image"]:
            sent_success = send_telegram_photo(CHAT_ID, ad["image"], caption)
        else:
            sent_success = send_telegram_message(CHAT_ID, caption)

        if sent_success:
            mark_sent(ad["id"])
            print(f"تم الإرسال بنجاح: {ad['title']}")
            time.sleep(2)


if __name__ == "__main__":
    process_and_send()