from datetime import datetime
import os
import sqlite3
import time
import pytz
import requests
from bs4 import BeautifulSoup

# --- إعدادات توقيت الإمارات (UAE Time) ---
UAE_TZ = pytz.timezone("Asia/Dubai")


def get_uae_time():
    return datetime.now(UAE_TZ).strftime("%Y-%m-%d %H:%M:%S")


# --- إعدادات البوت والخدمات من متغيرات البيئة ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
SCRAPINGANT_API_KEY = os.getenv("SCRAPINGANT_API_KEY")
SCRAPINGANT_API_KEY2 = os.getenv("SCRAPINGANT_API_KEY2")

DB_FILE = "sent_ads.db"

# --- الرابط المستهدف (تويوتا فقط) ---
TARGET_URLS = [
    {
        "name": "تويوتا (مالك أول)",
        "url": "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?seller_type=OW&badges=First%20Owner&sorting=date_desc",
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
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

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
    cursor.execute(
        "INSERT OR IGNORE INTO sent_ads (ad_id) VALUES (?)", (str(ad_id),)
    )
    conn.commit()


def fetch_with_fallback(target_url, target_name):
    """محاولة جلب الصفحة عبر المنصات بالترتيب مع فاصل زمني لتجنب الضغط"""

    # 1. المحاولة الأولى عبر ScraperAPI
    if SCRAPER_API_KEY:
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true&country_code=ae"
        try:
            print(f"[{get_uae_time()}] [{target_name}] محاولة الجلب عبر ScraperAPI...")
            res = requests.get(proxy_url, timeout=90)
            if res.status_code == 200:
                print(f"[{get_uae_time()}] نجح الجلب عبر ScraperAPI بنجاح.")
                return res.text
            else:
                print(
                    f"[{get_uae_time()}] ScraperAPI فشل برمز استجابة:"
                    f" {res.status_code}"
                )
        except Exception as e:
            print(f"[{get_uae_time()}] خطأ في الاتصال بـ ScraperAPI: {e}")

        time.sleep(3)

    # 2. المحاولة الثانية عبر ScrapingAnt (الأول)
    if SCRAPINGANT_API_KEY:
        proxy_url = f"https://api.scrapingant.com/v2/general?url={requests.utils.quote(target_url)}&x-api-key={SCRAPINGANT_API_KEY}&browser=true"
        try:
            print(
                f"[{get_uae_time()}] [{target_name}] التحويل التلقائي إلى"
                " ScrapingAnt (1)..."
            )
            res = requests.get(proxy_url, timeout=90)
            if res.status_code == 200:
                print(f"[{get_uae_time()}] نجح الجلب عبر ScrapingAnt (1) بنجاح.")
                return res.text
            else:
                print(
                    f"[{get_uae_time()}] ScrapingAnt (1) فشل برمز استجابة:"
                    f" {res.status_code}"
                )
        except Exception as e:
            print(f"[{get_uae_time()}] خطأ في الاتصال بـ ScrapingAnt (1): {e}")

        time.sleep(3)

    # 3. المحاولة الثالثة والأخيرة عبر ScrapingAnt (الثاني)
    if SCRAPINGANT_API_KEY2:
        proxy_url = f"https://api.scrapingant.com/v2/general?url={requests.utils.quote(target_url)}&x-api-key={SCRAPINGANT_API_KEY2}&browser=true"
        try:
            print(
                f"[{get_uae_time()}] [{target_name}] التحويل التلقائي إلى ScrapingAnt (2)..."
            )
            res = requests.get(proxy_url, timeout=90)
            if res.status_code == 200:
                print(f"[{get_uae_time()}] نجح الجلب عبر ScrapingAnt (2) بنجاح.")
                return res.text
            else:
                print(
                    f"[{get_uae_time()}] ScrapingAnt (2) فشل برمز استجابة: {res.status_code}"
                )
        except Exception as e:
            print(f"[{get_uae_time()}] خطأ في الاتصال بـ ScrapingAnt (2): {e}")

    return None


def fetch_dubizzle_ads_for_target(target_info):
    target_name = target_info["name"]
    target_url = target_info["url"]

    print(f"\n--- [{get_uae_time()}] جاري فحص: {target_name} ---")

    html_content = fetch_with_fallback(target_url, target_name)

    if not html_content:
        print(f"فشل جلب الصفحة لجميع المنصات المتاحة لـ {target_name}")
        return []

    ads_list = []
    try:
        soup = BeautifulSoup(html_content, "html.parser")

        listing_anchors = soup.find_all(
            "a", attrs={"data-testid": lambda val: val and val.startswith("listing-")}
        )

        if not listing_anchors:
            listing_anchors = soup.select("div#listing-card-wrapper a")

        seen_links = set()

        for a in listing_anchors:
            href = a.get("href", "")
            if not href or href in seen_links:
                continue

            if "/motors/" not in href:
                continue

            seen_links.add(href)

            clean_link = href.split("?")[0].rstrip("/")
            parts = [p for p in clean_link.split("/") if p]
            ad_id = parts[-1] if parts else str(hash(href))

            price_elem = a.find(attrs={"data-testid": "listing-price"})
            price = price_elem.text.strip() if price_elem else "غير معلن"

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

            year_elem = a.find(attrs={"data-testid": "listing-year"})
            year = year_elem.text.strip() if year_elem else "غير محدد"

            km_elem = a.find(attrs={"data-testid": "listing-kilometers"})
            km = km_elem.text.strip() if km_elem else "غير محدد"

            loc_elem = a.find(attrs={"data-testid": "listing-location"})
            location = loc_elem.text.strip() if loc_elem else "الإمارات"

            image_url = None
            gallery_div = a.find(attrs={"data-testid": "image-gallery"})
            if gallery_div:
                img_tag = gallery_div.find(
                    "img", src=lambda s: s and "dbz-images.dubizzle.com" in s
                )
                if img_tag:
                    image_url = img_tag.get("src")

            if not image_url:
                img_tag = a.find(
                    "img", src=lambda s: s and "dbz-images.dubizzle.com" in s
                )
                if img_tag:
                    image_url = img_tag.get("src")

            full_url = (
                href if href.startswith("http") else f"https://uae.dubizzle.com{href}"
            )

            ads_list.append({
                "id": ad_id,
                "category": target_name,
                "title": title,
                "price": price,
                "year": year,
                "km": km,
                "location": location,
                "image": image_url,
                "link": full_url,
            })

            if len(ads_list) >= 5:
                break

    except Exception as e:
        print(f"خطأ أثناء تحليل البيانات لـ {target_name}: {e}")

    return ads_list


def process_and_send():
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
                print(f"[{get_uae_time()}] تم إرسال الإعلان بنجاح: {ad['title']}")
                time.sleep(2)

        time.sleep(5)


if __name__ == "__main__":
    process_and_send()