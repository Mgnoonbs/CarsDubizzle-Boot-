import os
import sqlite3
import time
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

# --- إعدادات توقيت الإمارات (UAE Time) ---
UAE_TZ = pytz.timezone("Asia/Dubai")


def get_uae_time():
    return datetime.now(UAE_TZ).strftime("%Y-%m-%d %I:%M %p")


def escape_markdown(text):
    if not text:
        return ""
    for char in ['_', '*', '`', '[']:
        text = str(text).replace(char, f"\\{char}")
    return text


# --- إعدادات البوت والخدمات من متغيرات البيئة ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# الاعتماد حصرياً على ScrapingAnt مع حسابين تبادليين
SCRAPINGANT_API_KEY = os.getenv("SCRAPINGANT_API_KEY")
SCRAPINGANT_API_KEY2 = os.getenv("SCRAPINGANT_API_KEY2")

DB_FILE = "sent_ads.db"

# --- قائمة الروابط المستهدفة ---
TARGET_URLS = [
    {
        "name": "تويوتا (مالك أول)",
        "url": "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?sorting=date_desc&seller_type=OW",
    },
    {
        "name": "نيسان باترول (مالك أول)",
        "url": "https://uae.dubizzle.com/ar/motors/used-cars/nissan/patrol/?sorting=date_desc&seller_type=OW",
    },
    {
        "name": "لكزس LX-Series (مالك أول)",
        "url": "https://uae.dubizzle.com/ar/motors/used-cars/lexus/lx-series/?sorting=date_desc&seller_type=OW",
    },
    {
        "name": "هيونداي (مالك أول)",
        "url": "https://uae.dubizzle.com/ar/motors/used-cars/hyundai/?sorting=date_desc&seller_type=OW",
    },
]


def send_telegram_photo(chat_id, photo_url, caption):
    """إرسال صورة مع النص المصاحب عبر تليجرام"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "Markdown",
        }
        response = requests.post(url, data=payload, timeout=20)
        if response.status_code != 200:
            return send_telegram_message(chat_id, caption)
        return True
    except Exception:
        return send_telegram_message(chat_id, caption)


def send_telegram_message(chat_id, text):
    """إرسال رسالة نصية فقط"""
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
    except Exception:
        return False


# --- إدارة قاعدة البيانات ---
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


def fetch_with_scrapingant(target_url, target_name):
    """جلب المحتوى عبر ScrapingAnt فقط مع استخدام الحسابين التبادليين"""
    
    # 1. المحاولة بالحساب الأول
    if SCRAPINGANT_API_KEY:
        try:
            print(f"[{get_uae_time()}] [{target_name}] جاري الجلب عبر ScrapingAnt (الحساب الأول)...")
            ant_api_url = "https://api.scrapingant.com/v2/general"
            params = {
                "x-api-key": SCRAPINGANT_API_KEY,
                "url": target_url,
                "browser": "true",
                "proxy_country": "AE"
            }
            res = requests.get(ant_api_url, params=params, timeout=90)
            if res.status_code == 200 and len(res.text) > 5000:
                print(f"[{get_uae_time()}] نجح الجلب عبر ScrapingAnt (الحساب الأول).")
                return res.text
            print(f"[{get_uae_time()}] فشل ScrapingAnt (1) بكود: {res.status_code}")
        except Exception as e:
            print(f"[{get_uae_time()}] خطأ في ScrapingAnt (1): {e}")

        time.sleep(2)

    # 2. المحاولة بالحساب الثاني عند الحاجة
    if SCRAPINGANT_API_KEY2:
        try:
            print(f"[{get_uae_time()}] [{target_name}] التبديل إلى ScrapingAnt (الحساب الثاني)...")
            ant_api_url = "https://api.scrapingant.com/v2/general"
            params = {
                "x-api-key": SCRAPINGANT_API_KEY2,
                "url": target_url,
                "browser": "true",
                "proxy_country": "AE"
            }
            res = requests.get(ant_api_url, params=params, timeout=90)
            if res.status_code == 200 and len(res.text) > 5000:
                print(f"[{get_uae_time()}] نجح الجلب عبر ScrapingAnt (الحساب الثاني).")
                return res.text
            print(f"[{get_uae_time()}] فشل ScrapingAnt (2) بكود: {res.status_code}")
        except Exception as e:
            print(f"[{get_uae_time()}] خطأ في ScrapingAnt (2): {e}")

    return None


def fetch_dubizzle_ads_for_target(target_info):
    target_name = target_info["name"]
    target_url = target_info["url"]

    print(f"\n--- [{get_uae_time()}] جاري فحص: {target_name} ---")

    html_content = fetch_with_scrapingant(target_url, target_name)

    if not html_content:
        print(f"فشل جلب الصفحة عبر ScrapingAnt لـ {target_name}")
        return []

    ads_list = []
    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # الاستفادة من محددات كودك السابق والدقيقة لموقع Dubizzle
        listing_anchors = soup.find_all(
            "a", attrs={"data-testid": lambda val: val and val.startswith("listing-")}
        )

        if not listing_anchors:
            listing_anchors = soup.select("div#listing-card-wrapper a")
            
        if not listing_anchors:
            listing_anchors = soup.find_all("a", href=re.compile(r"/motors/used-cars/.*"))

        seen_links = set()

        for a in listing_anchors:
            href = a.get("href", "")
            if not href or href in seen_links or "/motors/used-cars/" not in href or href.endswith("/used-cars/"):
                continue

            seen_links.add(href)

            # استخراج ad_id من الرابط بشكل دقيق
            clean_link = href.split("?")[0].rstrip("/")
            parts = [p for p in clean_link.split("/") if p]
            
            # محاولة البحث عن المعرف الرقمي في الرابط
            id_match = re.search(r'-(\d+)(?:/|$)', clean_link)
            if id_match:
                ad_id = id_match.group(1)
            else:
                ad_id = parts[-1] if parts else str(hash(href))

            # السعر
            price_elem = a.find(attrs={"data-testid": "listing-price"})
            if price_elem:
                price = price_elem.text.strip()
            else:
                price_match = re.search(r'(?:AED|درهم)\s*([\d,]+)|([\d,]+)\s*(?:AED|درهم)', a.get_text(" ", strip=True))
                price = (price_match.group(1) or price_match.group(2)) if price_match else "غير معلن"

            # العنوان
            subheading = a.find(attrs={"data-testid": "subheading-text"})
            if subheading:
                title = subheading.text.strip()
            else:
                headings = a.find_all(
                    attrs={"data-testid": lambda v: v and v.startswith("heading-text-")}
                )
                title = (
                    " ".join([h.text.strip() for h in headings])
                    if headings
                    else target_name
                )

            # السنة / الموديل
            year_elem = a.find(attrs={"data-testid": "listing-year"})
            if year_elem:
                year = year_elem.text.strip()
            else:
                year_match = re.search(r'\b(19\d{2}|20[0-2]\d)\b', a.get_text(" ", strip=True))
                year = year_match.group(1) if year_match else "غير محدد"

            # الممشى
            km_elem = a.find(attrs={"data-testid": "listing-kilometers"})
            if km_elem:
                km = km_elem.text.strip()
            else:
                km_match = re.search(r'([\d,]+\s*(?:km|كم|كيلومتر))', a.get_text(" ", strip=True), re.IGNORECASE)
                km = km_match.group(1) if km_match else "غير محدد"

            # الموقع
            loc_elem = a.find(attrs={"data-testid": "listing-location"})
            location = loc_elem.text.strip() if loc_elem else "الإمارات"

            # الصورة
            image_url = None
            gallery_div = a.find(attrs={"data-testid": "image-gallery"})
            if gallery_div:
                img_tag = gallery_div.find(
                    "img", src=lambda s: s and ("dbz-images.dubizzle.com" in s or "http" in s)
                )
                if img_tag:
                    image_url = img_tag.get("src") or img_tag.get("data-src")

            if not image_url:
                img_tag = a.find(
                    "img", src=lambda s: s and ("dbz-images.dubizzle.com" in s or "http" in s)
                )
                if img_tag:
                    image_url = img_tag.get("src") or img_tag.get("data-src")

            full_url = href if href.startswith("http") else f"https://uae.dubizzle.com{href}"

            ads_list.append({
                "id": ad_id,
                "category": escape_markdown(target_name),
                "title": escape_markdown(title),
                "price": escape_markdown(price),
                "year": escape_markdown(year),
                "km": escape_markdown(km),
                "location": escape_markdown(location),
                "image": image_url,
                "link": full_url,
            })

            if len(ads_list) >= 10:
                break

    except Exception as e:
        print(f"خطأ أثناء تحليل البيانات لـ {target_name}: {e}")

    return ads_list


def process_and_send():
    init_db()
    print(
        f"[{get_uae_time()}] بدء جلب ومعالجة الإعلانات للفئات المستهدفة (توقيت"
        " الإمارات)..."
    )

    for target in TARGET_URLS:
        ads = fetch_dubizzle_ads_for_target(target)
        print(f"تم العثور على {len(ads)} إعلان في قسم [{target['name']}].")

        if not ads:
            continue

        for ad in ads:
            if is_already_sent(ad["id"]):
                print(f"الإعلان ({ad['id']}) مكرر وتم إرساله مسبقاً.")
                continue

            caption = (
                f"🚘 *إعلان جديد: {ad['category']}*\n\n"
                f"🚗 *السيارة:* {ad['title']}\n"
                f"💰 *السعر:* {ad['price']} درهم\n"
                f"📅 *الموديل:* {ad['year']}\n"
                f"🛣️ *الممشى:* {ad['km']}\n"
                f"📍 *الموقع:* {ad['location']}\n"
                f"⏰ *وقت الإشعار:* {get_uae_time()} (توقيت الإمارات)\n\n"
                f"🔗 [اضغط هنا لمشاهدة تفاصيل الإعلان]({ad['link']})"
            )

            sent_success = False
            if ad["image"]:
                sent_success = send_telegram_photo(CHAT_ID, ad["image"], caption)
            else:
                sent_success = send_telegram_message(CHAT_ID, caption)

            if sent_success:
                mark_sent(ad["id"])
                print(f"[{get_uae_time()}] تم إرسال الإعلان بنجاح: {ad['title']}")
                time.sleep(2)

        time.sleep(3)


if __name__ == "__main__":
    process_and_send()