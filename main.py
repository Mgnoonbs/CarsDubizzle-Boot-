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
    """جلب المحتوى عبر ScrapingAnt"""
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


def parse_ads_advanced(soup):
    """استخراج الإعلانات بدقة عالية عبر البحث الشامل في جميع وسوم script و HTML"""
    ads = []
    seen_ids = set()

    # 1. البحث في كافة وسوم script التي تحتوي على JSON
    for script in soup.find_all("script"):
        if not script.string:
            continue
        
        # البحث عن أنماط الإعلانات داخل JSON
        if "listing" in script.string or "price" in script.string or "motors" in script.string:
            try:
                # محاولة استخراج كافة الكائنات التي تشبه الإعلان
                raw_matches = re.findall(r'\{[^{}]*"id"[^{}]*\}', script.string)
                for match in raw_matches:
                    try:
                        item = json.loads(match)
                        ad_id = str(item.get("id") or item.get("listing_id") or "")
                        if ad_id and ad_id not in seen_ids and len(ad_id) >= 5:
                            seen_ids.add(ad_id)
                            ads.append(item)
                    except Exception:
                        continue
            except Exception:
                pass

    # 2. استخراج شامل ومحسّن من بطاقات HTML المباشرة
    cards = soup.find_all(["article", "div", "a"], attrs={"aria-label": True}) + \
            soup.find_all("a", href=re.compile(r"/motors/used-cars/toyota/.*"))

    for card in cards:
        href = card.get("href", "")
        if not href or "/used-cars/toyota/?" in href or href.endswith("/toyota/"):
            continue

        # استخراج رقم الإعلان من الرابط
        ad_id_match = re.search(r'-(\d+)(?:/|\?|$)', href)
        if not ad_id_match:
            ad_id_match = re.search(r'/(\d+)(?:/|\?|$)', href)
        
        if not ad_id_match:
            continue

        ad_id = ad_id_match.group(1)
        if ad_id in seen_ids:
            continue

        seen_ids.add(ad_id)

        # استخراج النص الكامل للبطاقة
        card_text = card.get_text(" ", strip=True)

        # 1. السعر (بحث عن رقم متبوع بـ AED/درهم أو العكس)
        price_match = re.search(r'(?:AED|درهم)\s*([\d,]+)|([\d,]+)\s*(?:AED|درهم)', card_text)
        price = "غير معلن"
        if price_match:
            price = price_match.group(1) or price_match.group(2)

        # 2. الموديل / السنة
        year_match = re.search(r'\b(19\d{2}|20[0-2]\d)\b', card_text)
        year = year_match.group(1) if year_match else "غير محدد"

        # 3. الممشى (كيلومترات)
        km_match = re.search(r'([\d,]+\s*(?:km|كم|كيلومتر))', card_text, re.IGNORECASE)
        km = km_match.group(1) if km_match else "غير محدد"

        # 4. العنوان
        title_elem = card.find(["h2", "h3", "strong", "span"])
        title = title_elem.text.strip() if title_elem else "تويوتا مستعملة"
        if len(title) < 5:
            title = f"تويوتا {year}"

        # 5. الصورة
        img_tag = card.find("img")
        img_url = None
        if img_tag:
            img_url = img_tag.get("src") or img_tag.get("data-src")
            if img_url and img_url.startswith("data:"):
                img_url = None

        full_url = href if href.startswith("http") else f"https://uae.dubizzle.com{href}"

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


def fetch_dubizzle_ads():
    target_url = "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?sorting=date_desc&seller_type=OW"
    html_content = fetch_html_content(target_url)

    if not html_content:
        print("فشل جلب محتوى الصفحة عبر ScrapingAnt.")
        return []

    soup = BeautifulSoup(html_content, "html.parser")
    ads_list = parse_ads_advanced(soup)

    return ads_list[:15]


def process_and_send():
    init_db()
    print("بدء جلب ومعالجة الإعلانات...")
    ads = fetch_dubizzle_ads()
    print(f"تم العثور على {len(ads)} إعلان تويوتا حقيقي.")

    if not ads:
        print("لم يتم العثور على إعلانات من الموقع.")
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
        if ad.get("image"):
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