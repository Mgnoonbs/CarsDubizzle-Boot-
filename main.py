import os
import sqlite3
import time
import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

# --- إعدادات البوت والخدمات من متغيرات البيئة ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# المفاتيح الخاصة بـ ScrapingAnt فقط
SCRAPINGANT_API_KEY = os.getenv("SCRAPINGANT_API_KEY")
SCRAPINGANT_API_KEY2 = os.getenv("SCRAPINGANT_API_KEY2")

DB_FILE = "sent_ads.db"
UAE_TZ = pytz.timezone("Asia/Dubai")


def get_uae_time_str():
    now = datetime.now(UAE_TZ)
    return now.strftime("%Y-%m-%d %I:%M %p")


def escape_markdown(text):
    if not text:
        return ""
    for char in ['_', '*', '`', '[']:
        text = str(text).replace(char, f"\\{char}")
    return text


def send_telegram_photo(chat_id, photo_url, caption):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, data=payload, timeout=20)
        if response.status_code != 200:
            print(f"فشل إرسال الصورة ({response.text})، جاري الإرسال كنص فقط...")
            return send_telegram_message(chat_id, caption)
        return True
    except Exception as e:
        print(f"خطأ أثناء إرسال الصورة: {e}")
        return send_telegram_message(chat_id, caption)


def send_telegram_message(chat_id, text):
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


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_ads (
            ad_id TEXT PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()


def is_already_sent(ad_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM sent_ads WHERE ad_id = ?", (str(ad_id),))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def mark_sent(ad_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO sent_ads (ad_id) VALUES (?)", (str(ad_id),))
    conn.commit()
    conn.close()


def fetch_html_content(target_url):
    """جلب المحتوى باستخدام ScrapingAnt حصراً (التدوير بين الحساب الأول والثاني)"""
    
    # 1. ScrapingAnt (الحساب الأول)
    if SCRAPINGANT_API_KEY:
        print("جاري الاتصال عبر ScrapingAnt (الحساب الأول)...")
        try:
            ant_api_url = "https://api.scrapingant.com/v2/general"
            params = {
                "x-api-key": SCRAPINGANT_API_KEY,
                "url": target_url,
                "browser": "true",
                "proxy_country": "AE"
            }
            res = requests.get(ant_api_url, params=params, timeout=90)
            print(f"حالة استجابة ScrapingAnt (1): {res.status_code} | الطول: {len(res.text)}")
            if res.status_code == 200 and len(res.text) > 5000:
                return res.text
            print(f"فشل ScrapingAnt (1) (كود: {res.status_code})، جاري التبديل للحساب الثاني...")
        except Exception as e:
            print(f"خطأ في ScrapingAnt (1): {e}")

    # 2. ScrapingAnt (الحساب الثاني)
    if SCRAPINGANT_API_KEY2:
        print("جاري الاتصال عبر ScrapingAnt (الحساب الثاني)...")
        try:
            ant_api_url = "https://api.scrapingant.com/v2/general"
            params = {
                "x-api-key": SCRAPINGANT_API_KEY2,
                "url": target_url,
                "browser": "true",
                "proxy_country": "AE"
            }
            res = requests.get(ant_api_url, params=params, timeout=90)
            print(f"حالة استجابة ScrapingAnt (2): {res.status_code} | الطول: {len(res.text)}")
            if res.status_code == 200 and len(res.text) > 5000:
                return res.text
            print(f"فشل ScrapingAnt (2) (كود: {res.status_code}).")
        except Exception as e:
            print(f"خطأ في ScrapingAnt (2): {e}")

    return None


def extract_ads_from_html(soup):
    """استخراج الإعلانات من عناصر HTML المباشرة"""
    ads = []
    cards = soup.find_all("a", href=re.compile(r"/motors/used-cars/toyota/.*"))
    seen_ids = set()

    for card in cards:
        href = card.get("href", "")
        if not href or href in seen_ids or "/used-cars/toyota/?" in href or href.endswith("/toyota/"):
            continue

        clean_link = href.split("?")[0].rstrip("/")
        parts = [p for p in clean_link.split("/") if p]
        ad_id = parts[-1] if parts else ""
        if not ad_id or ad_id in seen_ids:
            continue

        seen_ids.add(ad_id)

        title_elem = card.find(["h2", "h3", "strong", "span"], attrs={"data-testid": re.compile(r"heading|title")})
        title = title_elem.text.strip() if title_elem else "تويوتا مستعملة"

        price_elem = card.find(string=re.compile(r"AED|\d+,\d+|درهم"))
        price = price_elem.strip() if price_elem else "غير معلن"

        text_content = card.get_text(" ", strip=True)
        year_match = re.search(r"\b(20[0-2][0-9]|19[9][0-9])\b", text_content)
        year = year_match.group(1) if year_match else "غير محدد"

        km_match = re.search(r"(\d+[\d,]*\s*(km|كم))", text_content, re.IGNORECASE)
        km = km_match.group(1) if km_match else "غير محدد"

        full_url = href if href.startswith("http") else f"https://uae.dubizzle.com{href}"
        img_tag = card.find("img")
        img_url = None
        if img_tag:
            img_url = img_tag.get("src") or img_tag.get("data-src")
            if img_url and img_url.startswith("data:"):
                img_url = None

        ads.append({
            "id": ad_id,
            "title": escape_markdown(title),
            "price": escape_markdown(price),
            "year": escape_markdown(year),
            "km": escape_markdown(km),
            "location": "الإمارات",
            "seller_type": "المالك المباشر",
            "image": img_url,
            "link": full_url
        })

    return ads


def extract_ads_from_json(soup):
    """استخراج الإعلانات من كائن __NEXT_DATA__"""
    ads = []
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if not script_tag or not script_tag.string:
        return ads

    try:
        data = json.loads(script_tag.string)
        results = []

        def search_dict(d):
            if isinstance(d, dict):
                if ("listing_id" in d or "id" in d) and ("price" in d or "title" in d):
                    results.append(d)
                for v in d.values():
                    search_dict(v)
            elif isinstance(d, list):
                for item in d:
                    search_dict(item)

        search_dict(data)

        for item in results:
            ad_id = str(item.get("id") or item.get("listing_id") or "")
            if not ad_id or len(ad_id) < 3:
                continue

            title = item.get("title") or item.get("name") or "تويوتا مستعملة"

            price_val = item.get("price")
            if isinstance(price_val, dict):
                price = str(price_val.get("value", "غير معلن"))
            else:
                price = str(price_val) if price_val else "غير معلن"

            year = str(item.get("year") or "غير محدد")
            km = str(item.get("kilometers") or item.get("kms") or "غير محدد")

            url_path = item.get("absolute_url") or item.get("url") or ""
            if not url_path:
                continue
            full_url = url_path if url_path.startswith("http") else f"https://uae.dubizzle.com{url_path}"

            photos = item.get("photos", []) or item.get("images", [])
            image_url = None
            if photos and isinstance(photos, list) and len(photos) > 0:
                first_photo = photos[0]
                image_url = first_photo.get("main") if isinstance(first_photo, dict) else str(first_photo)

            ads.append({
                "id": ad_id,
                "title": escape_markdown(title),
                "price": escape_markdown(price),
                "year": escape_markdown(year),
                "km": escape_markdown(km),
                "location": "الإمارات",
                "seller_type": "المالك المباشر",
                "image": image_url,
                "link": full_url
            })
    except Exception as e:
        print(f"خطأ أثناء استخراج JSON: {e}")

    return ads


def fetch_dubizzle_ads():
    target_url = "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?sorting=date_desc&seller_type=OW"
    html_content = fetch_html_content(target_url)

    if not html_content:
        print("فشل جلب محتوى الصفحة عبر ScrapingAnt.")
        return []

    soup = BeautifulSoup(html_content, "html.parser")

    ads_list = extract_ads_from_json(soup)

    if not ads_list:
        print("لم يتم العثور على بيانات JSON، جاري التبديل لمعالجة عناصر HTML...")
        ads_list = extract_ads_from_html(soup)

    return ads_list[:15]


def process_and_send():
    init_db()
    print("بدء جلب ومعالجة الإعلانات...")
    ads = fetch_dubizzle_ads()
    print(f"تم العثور على {len(ads)} إعلان تويوتا حقيقي.")

    if not ads:
        print("لم يتم العثور على إعلانات من الموقع (تم الإلغاء بدون إرسال تنبيه).")
        return

    new_ads_sent_count = 0
    uae_time = get_uae_time_str()

    for ad in ads:
        if is_already_sent(ad["id"]):
            print(f"الإعلان {ad['id']} تم إرساله سابقاً.")
            continue

        caption = (
            f"🚘 *إعلان تويوتا جديد*\n\n"
            f"🚗 *السيارة:* {ad['title']}\n"
            f"👤 *المالك:* {ad['seller_type']}\n"
            f"💰 *السعر:* {ad['price']} درهم\n"
            f"📅 *الموديل:* {ad['year']}\n"
            f"🛣️ *الممشى:* {ad['km']}\n"
            f"📍 *الموقع:* {ad['location']}\n"
            f"⏰ *وقت الإشعار:* {uae_time} (توقيت الإمارات)\n\n"
            f"🔗 [اضغط هنا لمشاهدة تفاصيل الإعلان]({ad['link']})"
        )

        sent_success = False
        if ad["image"]:
            print(f"جاري إرسال الإعلان مع الصورة: {ad['image']}")
            sent_success = send_telegram_photo(CHAT_ID, ad["image"], caption)
        else:
            print("لم يتم العثور على صورة للإعلان، جاري الإرسال كنص فقط...")
            sent_success = send_telegram_message(CHAT_ID, caption)

        if sent_success:
            mark_sent(ad["id"])
            new_ads_sent_count += 1
            print(f"تم الإرسال بنجاح: {ad['title']}")
            time.sleep(2)

    if new_ads_sent_count == 0:
        print("جميع الإعلانات المجلوبة تم إرسالها سابقاً.")


if __name__ == "__main__":
    process_and_send()