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

SCRAPINGANT_KEYS = [
    os.getenv(f"SCRAPINGANT_API_KEY{i}" if i > 1 else "SCRAPINGANT_API_KEY")
    for i in range(1, 8)
]
SCRAPINGANT_KEYS = [k for k in SCRAPINGANT_KEYS if k]

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
    # 1. المحاولة عبر ScraperAPI
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

    # 2. المحاولة عبر مفاتيح ScrapingAnt (مع انتظار أطول نسبياً وتحسين الباراميترات)
    for idx, key in enumerate(SCRAPINGANT_KEYS, start=1):
        proxy_url = f"https://api.scrapingant.com/v2/general?url={requests.utils.quote(target_url)}&x-api-key={key}&browser=true&wait_for_selector=a"
        try:
            print(
                f"[{get_uae_time()}] [{target_name}] التحويل التلقائي إلى"
                f" ScrapingAnt ({idx})..."
            )
            res = requests.get(proxy_url, timeout=90)
            if res.status_code == 200:
                print(
                    f"[{get_uae_time()}] نجح الجلب عبر ScrapingAnt ({idx}) بنجاح."
                )
                return res.text
            else:
                print(
                    f"[{get_uae_time()}] ScrapingAnt ({idx}) فشل برمز استجابة:"
                    f" {res.status_code}"
                )
        except Exception as e:
            print(
                f"[{get_uae_time()}] خطأ في الاتصال بـ ScrapingAnt ({idx}): {e}"
            )
        time.sleep(3)

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

        # طباعة عنوان الصفحة للتشخيص في حال صفر نتائج
        page_title = soup.title.string.strip() if soup.title else "بدون عنوان"
        print(f"[{get_uae_time()}] عنوان الصفحة المستلمة: {page_title[:60]}")

        # محددات البحث الأساسية
        listing_anchors = soup.find_all(
            "a", attrs={"data-testid": lambda val: val and val.startswith("listing-")}
        )

        if not listing_anchors:
            listing_anchors = soup.select("div#listing-card-wrapper a")

        # محدد احتياطي أوسع لروابط السيارات
        if not listing_anchors:
            listing_anchors = [
                a
                for a in soup.find_all("a", href=True)
                if "/used-cars/" in a["href"] and len(a["href"].split("/")) > 4
            ]

        seen_links = set()

        for a in listing_anchors:
            href = a.get("href", "")
            if not href or href in seen_links:
                continue

            if "/motors/" not in href and "/used-cars/" not in href:
                continue

            seen_links.add(href)

            clean_link = href.split("?")[0].rstrip("/")
            parts = [p for p in clean_link.split("/") if p]
            ad_id = parts[-1] if parts else str(hash(href))

            # البحث عن عناصر داخل البطاقة الأب إن أمكن، أو من نفس العنصر
            card_parent = a.find_parent("div", class_=lambda c: c and ("card" in c or "listing" in c)) or a

            price_elem = card_parent.find(attrs={"data-testid": "listing-price"}) or card_parent.find(string=lambda s: s and "AED" in str(s))
            price = price_elem.text.strip() if hasattr(price_elem, 'text') else (str(price_elem).strip() if price_elem else "غير معلن")

            subheading = card_parent.find(attrs={"data-testid": "subheading-text"})
            if subheading:
                title = subheading.text.strip()
            else:
                headings = card_parent.find_all(
                    attrs={"data-testid": lambda v: v and v.startswith("heading-text-")}
                )
                title = (
                    " ".join([h.text.strip() for h in headings])
                    if headings
                    else (a.get("title") or target_name)
                )

            year_elem = card_parent.find(attrs={"data-testid": "listing-year"})
            year = year_elem.text.strip() if year_elem else "غير محدد"

            km_elem = card_parent.find(attrs={"data-testid": "listing-kilometers"})
            km = km_elem.text.strip() if km_elem else "غير محدد"

            loc_elem = card_parent.find(attrs={"data-testid": "listing-location"})
            location = loc_elem.text.strip() if loc_elem else "الإمارات"

            image_url = None
            img_tag = card_parent.find("img", src=lambda s: s and ("dbz-images" in s or "dubizzle" in s))
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
                f"💰 *السعر:* {ad['price']}\n"
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