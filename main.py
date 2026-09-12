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
            "disable_web_page_preview": False,
        }
        response = requests.post(url, data=payload, timeout=15)
        print(f"استجابة تليجرام: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"خطأ في إرسال تليجرام: {e}")
        return False


# --- إدارة قاعدة البيانات (تصفير السجلات للتجربة) ---
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("DROP TABLE IF EXISTS sent_ads")
cursor.execute("""
    CREATE TABLE sent_ads (
        ad_id TEXT PRIMARY KEY
    )
""")
conn.commit()


def is_sent(ad_id):
    cursor.execute("SELECT 1 FROM sent_ads WHERE ad_id = ?", (str(ad_id),))
    return cursor.fetchone() is not None


def mark_sent(ad_id):
    cursor.execute("INSERT OR IGNORE INTO sent_ads (ad_id) VALUES (?)", (str(ad_id),))
    conn.commit()


# --- الكشط المتقدم باستخدام Playwright ---
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
                "--window-size=1920,1080",
            ],
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept-Language": "ar-AE,ar;q=0.9,en-US;q=0.8,en;q=0.7",
                "Sec-Ch-Ua": '"Not;A=Brand";v="24", "Chromium";v="128", "Google Chrome";v="128"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )

        # تجاوز اكتشاف البوت
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = context.new_page()

        try:
            print(f"جاري فتح الرابط: {target_url}")
            page.goto(target_url, timeout=60000, wait_until="domcontentloaded")

            time.sleep(5)

            # التمرير لأسفل الصفحة لتنشيط تحميل الإعلانات (Lazy Loading)
            for _ in range(4):
                page.mouse.wheel(0, 800)
                time.sleep(1.5)

            # البحث عن عناصر الإعلانات
            cards = page.locator("div[data-testid='listing-card'], article, a[href*='/motors/used-cars/']").all()
            print(f"تم إيجاد {len(cards)} عنصر في الصفحة.")

            seen_links = set()
            for card in cards:
                try:
                    # استخراج الرابط
                    href = ""
                    if card.node_name() == "a":
                        href = card.get_attribute("href")
                    else:
                        link_el = card.locator("a[href*='/motors/used-cars/']").first
                        if link_el.count() > 0:
                            href = link_el.get_attribute("href")

                    if not href:
                        continue

                    if href.startswith("/"):
                        href = f"https://uae.dubizzle.com{href}"

                    clean_link = href.split("?")[0].rstrip("/")
                    parts = [p for p in clean_link.split("/") if p]

                    # استبعاد روابط الأقسام
                    if len(parts) <= 5 or parts[-1] in ["used-cars", "toyota", "motors", "ar"]:
                        continue

                    if clean_link in seen_links:
                        continue
                    seen_links.add(clean_link)

                    ad_id = parts[-1]

                    # استخراج العنوان
                    title = ""
                    text_content = card.inner_text().split("\n")
                    for t in text_content:
                        t_clean = t.strip()
                        if any(k in t_clean.lower() for k in ["toyota", "تويوتا", "camry", "land cruiser", "corolla", "hilux", "prado", "yaris"]):
                            title = t_clean
                            break

                    if not title and len(text_content) > 0:
                        title = text_content[0].strip()

                    if not title or len(title) < 3:
                        model_part = parts[-2] if len(parts) >= 2 else "Toyota"
                        title = f"Toyota {model_part.replace('-', ' ').title()}"

                    # استخراج السعر والمشاوير
                    price = "راجع الإعلان"
                    for t in text_content:
                        if "درهم" in t or "AED" in t:
                            price = t.strip()
                            break

                    ads_list.append({
                        "id": ad_id,
                        "title": title,
                        "price": price,
                        "link": clean_link,
                    })

                    if len(ads_list) >= 7:
                        break

                except Exception as ex_card:
                    continue

        except Exception as e:
            print(f"خطأ أثناء التصفح: {e}")
        finally:
            browser.close()

    return ads_list


def process_and_send():
    print("بدء عملية التصفح والإرسال إلى تليجرام...")
    ads = scrape_dubizzle_elements()
    print(f"إجمالي الإعلانات المستخرجة بنجاح: {len(ads)}")

    if not ads:
        print("لم تعثر على إعلانات، تأكد من حظر IP أو تحديث الرابط.")
        send_telegram_message(CHAT_ID, "⚠️ تعذر جلب الإعلانات من دوبيزل في هذه المحاولة (احتمال حجب أو عدم تحميل).")
        return

    for ad in ads:
        caption = (
            f"🚘 *إعلان جديد من المالك (Toyota)*\n\n"
            f"🚗 *{ad['title']}*\n"
            f"💰 הסعر: {ad['price']}\n"
            f"📍 الموقع: الإمارات\n\n"
            f"🔗 [اضغط هنا للفتح على دوبيزل]({ad['link']})"
        )

        success = send_telegram_message(CHAT_ID, caption)

        if success:
            mark_sent(ad["id"])
            print(f"تم إرسال الإعلان بنجاح: {ad['title']}")
            time.sleep(2)
        else:
            print(f"فشل إرسال الإعلان: {ad['title']}")


if __name__ == "__main__":
    process_and_send()