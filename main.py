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

# المزودات المعتمدة (حسابين ScraperAPI وحسابين ScrapingAnt)
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
SCRAPER_API_KEY2 = os.getenv("SCRAPER_API_KEY2")
SCRAPINGANT_API_KEY = os.getenv("SCRAPINGANT_API_KEY")
SCRAPINGANT_API_KEY2 = os.getenv("SCRAPINGANT_API_KEY2")

DB_FILE = "sent_ads.db"

# المنطقة الزمنية لدولة الإمارات (GST - UTC+4)
UAE_TZ = pytz.timezone("Asia/Dubai")


def get_uae_time_str():
    """الحصول على الوقت الحالي بتوقيت الإمارات بصيغة واضحة"""
    now = datetime.now(UAE_TZ)
    return now.strftime("%Y-%m-%d %I:%M %p")


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
        
        if response.status_code != 200:
            print(f"فشل إرسال الصورة ({response.text})، جاري الإرسال كنص فقط...")
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


def fetch_html_content(target_url):
    """دالة مرنة تحاول الجلب عبر المزودات بالترتيب: ScraperAPI (1) -> ScraperAPI (2) -> ScrapingAnt (1) -> ScrapingAnt (2)"""
    
    # 1. ScraperAPI (الحساب الأول)
    if SCRAPER_API_KEY:
        print("جاري الاتصال عبر ScraperAPI (الحساب الأول)...")
        try:
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true&keep_headers=true&cache=false"
            res = requests.get(proxy_url, timeout=60)
            print(f"حالة استجابة ScraperAPI (1): {res.status_code} | الطول: {len(res.text)}")
            if res.status_code == 200 and len(res.text) > 5000:
                return res.text
            print(f"فشل ScraperAPI (1) (كود: {res.status_code})، جاري التبديل...")
        except Exception as e:
            print(f"خطأ في ScraperAPI (1): {e}")

    # 2. ScraperAPI (الحساب الثاني)
    if SCRAPER_API_KEY2:
        print("جاري الاتصال عبر ScraperAPI (الحساب الثاني)...")
        try:
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY2}&url={target_url}&render=true&keep_headers=true&cache=false"
            res = requests.get(proxy_url, timeout=60)
            print(f"حالة استجابة ScraperAPI (2): {res.status_code} | الطول: {len(res.text)}")
            if res.status_code == 200 and len(res.text) > 5000:
                return res.text
            print(f"فشل ScraperAPI (2) (كود: {res.status_code})، جاري التبديل...")
        except Exception as e:
            print(f"خطأ في ScraperAPI (2): {e}")

    # 3. ScrapingAnt (الحساب الأول)
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
            print(f"فشل ScrapingAnt (1) (كود: {res.status_code})، جاري التبديل...")
        except Exception as e:
            print(f"خطأ في ScrapingAnt (1): {e}")

    # 4. ScrapingAnt (الحساب الثاني الاحتياطي)
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
            print(f"فشل ScrapingAnt (2) (كود: {res.status_code})، جاري التبديل...")
        except Exception as e:
            print(f"خطأ في ScrapingAnt (2): {e}")
            
    return None


def extract_ads_from_json(soup):
    """دالة مخصصة لاستخراج الإعلانات من كائن JSON الخاص بـ Next.js"""
    ads = []
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if not script_tag or not script_tag.string:
        return ads

    try:
        data = json.loads(script_tag.string)
        page_props = data.get("props", {}).get("pageProps", {})
        
        # الوصول لقائمة الإعلانات بداخل استجابة الصفحة
        results = page_props.get("results", []) or page_props.get("listings", []) or page_props.get("initialState", {}).get("listings", [])

        for item in results:
            if not isinstance(item, dict):
                continue
                
            ad_id = str(item.get("id") or item.get("listing_id") or "")
            title = item.get("title") or item.get("name") or "تويوتا مستعملة"
            
            # السعر
            price_val = item.get("price", {})
            price = str(price_val.get("value", "غير معلن")) if isinstance(price_val, dict) else str(item.get("price", "غير معلن"))
            
            # التفاصيل المرفقة
            year = str(item.get("year", "غير محدد"))
            km = str(item.get("kilometers", item.get("kms", "غير محدد")))
            location = item.get("location", {}).get("name", "الإمارات") if isinstance(item.get("location"), dict) else str(item.get("location", "الإمارات"))
            
            # الرابط
            url_path = item.get("absolute_url") or item.get("url") or ""
            full_url = url_path if url_path.startswith("http") else f"https://uae.dubizzle.com{url_path}"

            # الصورة
            photos = item.get("photos", []) or item.get("images", [])
            image_url = None
            if photos and isinstance(photos, list):
                first_photo = photos[0]
                image_url = first_photo.get("main") if isinstance(first_photo, dict) else str(first_photo)

            if ad_id and full_url:
                ads.append({
                    "id": ad_id,
                    "title": title,
                    "price": price,
                    "year": year,
                    "km": km,
                    "location": location,
                    "seller_type": "المالك المباشر / المالك الأول",
                    "image": image_url,
                    "link": full_url
                })
    except Exception as e:
        print(f"خطأ أثناء استخراج JSON: {e}")

    return ads


def fetch_dubizzle_ads():
    # الرابط يحتوي على فلاتر: الترتيب من الأحدث للأقدم + المالك المباشر OW + المالك الأول First Owner
    target_url = "https://uae.dubizzle.com/ar/motors/used-cars/toyota/?sorting=date_desc&seller_type=OW&badges=First%20Owner"
    html_content = fetch_html_content(target_url)

    if not html_content:
        print("فشل جلب محتوى الصفحة من كافة المزودات.")
        return []

    ads_list = []

    try:
        soup = BeautifulSoup(html_content, "html.parser")
        
        # 1. التجربة الأولى: الاستخراج المباشر عبر هيكل JSON المتوفر بـ __NEXT_DATA__
        ads_list = extract_ads_from_json(soup)
        
        # 2. التجربة الثانية: Fallback عبر DOM scraping إذا لم نجد عناصر في JSON
        if not ads_list:
            print("لم يتم العثور على بيانات JSON، جاري التبديل لمعالجة عناصر HTML...")
            listing_anchors = soup.find_all("a", href=lambda h: h and "/motors/used-cars/toyota/" in h and ("detail" in h or h.count('/') >= 6))

            if not listing_anchors:
                listing_anchors = soup.find_all("a", attrs={"data-testid": lambda val: val and val.startswith("listing-")})

            seen_links = set()

            for a in listing_anchors:
                href = a.get("href", "")
                if not href or href in seen_links or href.endswith('/toyota/') or 'sorting=' in href:
                    continue

                seen_links.add(href)
                
                clean_link = href.split("?")[0].rstrip("/")
                parts = [p for p in clean_link.split("/") if p]
                ad_id = parts[-1] if parts else str(hash(href))

                price_elem = a.find(attrs={"data-testid": "listing-price"}) or a.find(text=lambda t: t and ("درهم" in t or "AED" in t))
                price = price_elem.text.strip() if price_elem else "غير معلن"

                subheading = a.find(attrs={"data-testid": "subheading-text"})
                if subheading:
                    title = subheading.text.strip()
                else:
                    headings = a.find_all(["h2", "h3", "span"], attrs={"data-testid": lambda v: v and "heading" in str(v)})
                    title = " ".join([h.text.strip() for h in headings]) if headings else a.get_text(" ", strip=True)[:50]

                year_elem = a.find(attrs={"data-testid": "listing-year"})
                year = year_elem.text.strip() if year_elem else "غير محدد"

                km_elem = a.find(attrs={"data-testid": "listing-kilometers"})
                km = km_elem.text.strip() if km_elem else "غير محدد"

                loc_elem = a.find(attrs={"data-testid": "listing-location"})
                location = loc_elem.text.strip() if loc_elem else "الإمارات"

                badge_text = "المالك الأول" if "First Owner" in a.get_text() or "المالك الأول" in a.get_text() else "المالك المباشر"

                # استخراج الصورة
                image_url = None
                imgs = a.find_all("img")
                for img in imgs:
                    src = img.get("src") or img.get("data-src") or ""
                    if "dbz-images.dubizzle.com" in src and not src.startswith("data:image"):
                        image_url = src
                        break

                full_url = href if href.startswith("http") else f"https://uae.dubizzle.com{href}"

                ads_list.append({
                    "id": ad_id,
                    "title": title if title else "تويوتا مستعملة",
                    "price": price,
                    "year": year,
                    "km": km,
                    "location": location,
                    "seller_type": badge_text,
                    "image": image_url,
                    "link": full_url
                })
                if len(ads_list) >= 15:
                    break

    except Exception as e:
        print(f"خطأ أثناء تحليل البيانات: {e}")

    return ads_list[:15]


def process_and_send():
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
        print("جميع الإعلانات المجلوبة تم إرسالها سابقاً (تم السكوت وعدم إرسال رسالة تليجرام).")


if __name__ == "__main__":
    process_and_send()