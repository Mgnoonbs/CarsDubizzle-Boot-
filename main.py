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
        return response.status_code == 200
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
            "disable_web_page_preview": False
        }
        response = requests.post(url, data=payload, timeout=15)
        print(f"استجابة تليجرام: {response.status_code} - {response.text}")
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept-Language": "ar-AE,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )

        page = context.new_page()

        try:
            print(f"جاري فتح الرابط: {target_url}")
            page.goto(target_url, timeout=60000, wait_until="networkidle")
            time.sleep(5)

            # طباعة عنوان الصفحة للتأكد من عدم وجود Cloudflare Block
            print(f"عنوان الصفحة الحالي: {page.title()}")

            page.mouse.wheel(0, 1500)
            time.sleep(3)

            # البحث عن كافة الروابط المؤدية لإعلانات السيارات
            links = page.locator("a[href*='/motors/used-cars/']").all()
            print(f"إجمالي الروابط المكتشفة في الصفحة: {len(links)}")

            seen_links = set()
            for link_el in links:
                try:
                    href = link_el.get_attribute("href")
                    if not href:
                        continue

                    if href.startswith("/"):
                        href = f"https://uae.dubizzle.com{href}"

                    clean_link = href.split("?")[0].rstrip("/")
                    parts = [p for p in clean_link.split("/") if p]

                    # التصفية للوصول لروابط الإعلانات المباشرة فقط
                    if len(parts) <= 5 or parts[-1] in ["used-cars", "toyota", "motors"]:
                        continue

                    if clean_link in seen_links:
                        continue
                    seen_links.add(clean_link)

                    ad_id = parts[-1]

                    # محاولة استخراج عنوان مبدئي من نص الرابط أو الرابط نفسه
                    title_text = link_el.inner_text().strip()
                    if not title_text or len(title_text) < 3:
                        title_text = f"Toyota {parts[-2].replace('-', ' ').title()}"

                    ads_list.append({
                        "id": ad_id,
                        "title": title_text,
                        "price": "راجع الرابط للتفاصيل",
                        "year": "2024/2025",
                        "mileage": "غير محدد",
                        "link": clean_link,
                        "image_url": ""
                    })

                    if len(ads_list) >= 5:
                        break

                except Exception as ex_card:
                    continue

        except Exception as e:
            print(f"خطأ رئيسي أثناء التصفح: {e}")
        finally:
            browser.close()

    return ads_list


def process_and_send():
    print("بدء عملية الفحص والإرسال إلى تليجرام...")
    
    # فحص المتغيرات
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        print("خطأ: TELEGRAM_BOT_TOKEN أو CHAT_ID غير معرفة في GitHub Secrets!")
        return

    ads = scrape_dubizzle_elements()
    print(f"عدد الإعلانات المستخرجة للإرسال: {len(ads)}")

    if not ads:
        print("لم يتم العثور على إعلانات جديدة، جاري إرسال إشعار تجريبي لتأكيد الربط...")
        send_telegram_message(CHAT_ID, "⚠️ السكربت عمل بنجاح لكن لم يجد إعلانات جديدة في الصفحة الحالية.")
        return

    for ad in ads:
        caption = (
            f"🚘 *إعلان جديد على دوبيزل (Toyota)*\n\n"
            f"🚗 {ad['title']}\n"
            f"📍 الموقع: الإمارات\n\n"
            f"🔗 [اضغط هنا لمشاهدة الإعلان كاملًا]({ad['link']})"
        )

        success = send_telegram_message(CHAT_ID, caption)

        if success:
            mark_sent(ad["id"])
            print(f"تم إرسال الإعلان بنجاح: {ad['id']}")
            time.sleep(2)
        else:
            print(f"فشل إرسال الإعلان: {ad['id']}")


if __name__ == "__main__":
    process_and_send()