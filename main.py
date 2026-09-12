import os
import sqlite3
import time
from playwright.sync_api import sync_playwright
import requests

# --- إعدادات البوت من متغيرات البيئة (GitHub Secrets) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

DB_FILE = "sent_ads.db"


def send_telegram_photo(chat_id, photo_url, caption):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "Markdown",
        }
        response = requests.post(url, data=payload, timeout=20)
        if response.status_code == 200:
            return True

        payload["parse_mode"] = None
        response = requests.post(url, data=payload, timeout=20)
        if response.status_code == 200:
            return True

        return send_telegram_message(chat_id, caption)
    except Exception as e:
        print(f"خطأ في إرسال صورة تليجرام: {e}")
        return send_telegram_message(chat_id, caption)


def send_telegram_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        response = requests.post(url, data=payload, timeout=15)
        return response.status_code == 200
    except Exception as e:
        print(f"خطأ في إرسال تليجرام: {e}")
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


def is_sent(ad_id):
    cursor.execute("SELECT 1 FROM sent_ads WHERE ad_id = ?", (str(ad_id),))
    return cursor.fetchone() is not None


def mark_sent(ad_id):
    cursor.execute(
        "INSERT OR IGNORE INTO sent_ads (ad_id) VALUES (?)" , (str(ad_id),)
    )
    conn.commit()


# --- الكشط باستخدام Playwright ---
def scrape_dubizzle_elements():
    ads_list = []
    target_url = "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?sorting=date_desc&seller_type=OW"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = context.new_page()

        try:
            print(f"جاري فتح الرابط: {target_url}")
            page.goto(target_url, timeout=60000, wait_until="domcontentloaded")

            # الانتظار الخفيف للتأكد من انطلاق العناصر
            time.sleep(5)
            page.mouse.wheel(0, 1000)
            time.sleep(3)

            cards = page.locator(
                "div[data-testid='listing-card'], article, div[class*='Card']"
            ).all()
            print(f"تم العثور على {len(cards)} عنصر في الصفحة.")

            seen_links = set()
            for card in cards:
                try:
                    link_el = card.locator("a[href*='/motors/used-cars/']").first
                    if link_el.count() == 0:
                        continue

                    link = link_el.get_attribute("href")
                    if not link:
                        continue

                    if link.startswith("/"):
                        link = f"https://uae.dubizzle.com{link}"

                    clean_link = link.split("?")[0].rstrip("/")
                    parts = [p for p in clean_link.split("/") if p]

                    if len(parts) <= 4 or parts[-1] in ["used-cars", "toyota"]:
                        continue

                    if clean_link in seen_links:
                        continue
                    seen_links.add(clean_link)

                    ad_id = parts[-1]

                    # فحص إذا تم إرساله من قبل
                    if is_sent(ad_id):
                        print(f"الإعلان {ad_id} مرسل سابقاً، سيتم تخطيه.")
                        continue

                    title = ""
                    subheading_el = card.locator(
                        "h2[data-testid='subheading-text'], [data-testid='heading-text']"
                    ).first
                    if subheading_el.count() > 0:
                        title = subheading_el.inner_text().strip()

                    if not title:
                        t_els = card.locator("h3, h2, h1").all()
                        t_parts = [e.inner_text().strip() for e in t_els if e.inner_text().strip()]
                        if t_parts:
                            title = " ".join(t_parts[:2])

                    if not title or "معرض الشهر" in title:
                        if "toyota" in parts:
                            idx = parts.index("toyota")
                            if len(parts) > idx + 1:
                                model_name = parts[idx + 1].replace("-", " ").title()
                                title = f"Toyota {model_name}"

                    price = "غير مذكور"
                    price_el = card.locator("[data-testid='listing-price'], [class*='price']").first
                    if price_el.count() > 0:
                        price = price_el.inner_text().strip() + " درهم"

                    year = "غير مذكورة"
                    year_el = card.locator("[data-testid='listing-year']").first
                    if year_el.count() > 0:
                        year = year_el.inner_text().strip()

                    mileage = "غير مذكور"
                    km_el = card.locator("[data-testid='listing-kilometers']").first
                    if km_el.count() > 0:
                        mileage = km_el.inner_text().strip()

                    ads_list.append({
                        "id": ad_id,
                        "title": title,
                        "price": price,
                        "year": year,
                        "mileage": mileage,
                        "link": clean_link,
                    })

                    if len(ads_list) >= 10:
                        break

                except Exception as ex_card:
                    print(f"خطأ في معالجة الكارت: {ex_card}")
                    continue

            # استخراج روابط الصور العالية الجودة عبر الميتا تاج og:image
            for ad in ads_list:
                try:
                    detail_page = context.new_page()
                    detail_page.goto(ad["link"], timeout=20000, wait_until="domcontentloaded")
                    time.sleep(1)
                    
                    og_img = detail_page.locator("meta[property='og:image']").get_attribute("content")
                    if og_img and "http" in og_img:
                        ad["image_url"] = og_img
                    else:
                        img_el = detail_page.locator("img[src*='dubizzle'], img[src*='images']").first
                        ad["image_url"] = img_el.get_attribute("src") if img_el.count() > 0 else ""
                    
                    detail_page.close()
                except Exception as ex:
                    print(f"تعذر جلب صورة تفصيلية للإعلان {ad['id']}: {ex}")
                    ad["image_url"] = ""

        except Exception as e:
            print(f"خطأ رئيسي أثناء التصفح: {e}")
        finally:
            browser.close()

    return ads_list


def process_and_send():
    print("جاري فحص الإعلانات الجديدة حسب الترتيب والفلاتر...")
    ads = scrape_dubizzle_elements()
    print(f"عدد الإعلانات الجديدة التي سيتم إرسالها الآن: {len(ads)}")

    for ad in ads:
        caption = (
            f"🚘 *سيارة Toyota جديدة (من المالك)*\n\n"
            f"🚗 {ad['title']}\n"
            f"💰 السعر: {ad['price']}\n"
            f"📅 السنة: {ad['year']}\n"
            f"🛣️ الممشى: {ad['mileage']}\n"
            f"📍 الموقع: الإمارات\n\n"
            f"🔗 [رابط الإعلان على دوبيزل]({ad['link']})"
        )

        if ad.get("image_url"):
            success = send_telegram_photo(CHAT_ID, ad["image_url"], caption)
        else:
            success = send_telegram_message(CHAT_ID, caption)

        if success:
            mark_sent(ad["id"])
            print(f"تم إرسال الإعلان بنجاح: {ad['title']}")
            time.sleep(2)
        else:
            print(f"فشل إرسال الإعلان: {ad['title']}")


if __name__ == "__main__":
    process_and_send()