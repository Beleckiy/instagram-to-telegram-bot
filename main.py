import os
import time
import logging
import schedule
import instaloader
import threading
import http.server
import socketserver

from telegram import Bot
from telegram.error import TelegramError

# === Keep alive server on port 8080 ===
def keep_alive():
    PORT = 8080
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"🌐 Псевдосервер працює на порту {PORT}")
        httpd.serve_forever()

threading.Thread(target=keep_alive, daemon=True).start()

# === Environment Variables ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")

# === Logging ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
)
logger = logging.getLogger()

# === Telegram Bot ===
bot = Bot(token=TELEGRAM_TOKEN)

# === Shortcode cache ===
CACHE_FILE = "last_shortcode.txt"

def load_last_shortcode():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return f.read().strip()
    return ""

def save_last_shortcode(shortcode):
    with open(CACHE_FILE, "w") as f:
        f.write(shortcode)

# === Main logic ===
def send_latest_instagram_post():
    logger.info("🔍 Перевірка наявності нового поста...")
    try:
        loader = instaloader.Instaloader()

        # Login with credentials from environment
        if IG_USERNAME and IG_PASSWORD:
            loader.login(IG_USERNAME, IG_PASSWORD)
            logger.info("🔐 Успішний вхід в Instagram")
        else:
            logger.warning("⚠️ Не вказано IG_USERNAME або IG_PASSWORD. Спроба доступу без логіна.")

        profile = instaloader.Profile.from_username(loader.context, INSTAGRAM_USERNAME)
        posts = profile.get_posts()
        latest_post = next(posts)
        latest_shortcode = latest_post.shortcode

        last_sent = load_last_shortcode()
        if latest_shortcode == last_sent:
            logger.info("⏸ Нових постів немає.")
            return

        caption = latest_post.caption or "(без підпису)"
        media_path = f"{latest_shortcode}"

        loader.download_post(latest_post, target=media_path)

        # Знаходимо файл фото або відео
        media_file = None
        for fname in os.listdir(media_path):
            if fname.endswith(".jpg") or fname.endswith(".mp4"):
                media_file = os.path.join(media_path, fname)
                break

        # Відправка в Telegram
        if media_file:
            with open(media_file, "rb") as f:
                if media_file.endswith(".jpg"):
                    bot.send_photo(chat_id=CHAT_ID, photo=f, caption=caption)
                elif media_file.endswith(".mp4"):
                    bot.send_video(chat_id=CHAT_ID, video=f, caption=caption)
                logger.info(f"✅ Медіа надіслано: {media_file}")
        else:
            post_url = f"https://www.instagram.com/p/{latest_shortcode}/"
            bot.send_message(chat_id=CHAT_ID, text=f"📸 Новий пост в Instagram:\n{caption}\n{post_url}")
            logger.warning("⚠️ Не знайдено медіафайл, надіслано лише текст.")

        save_last_shortcode(latest_shortcode)

        # Очищення після себе
        for fname in os.listdir(media_path):
            os.remove(os.path.join(media_path, fname))
        os.rmdir(media_path)

    except TelegramError as e:
        logger.error(f"❌ Telegram error: {e}")
    except Exception as e:
        logger.error(f"❌ Інша помилка: {e}")

# === Scheduler ===
schedule.every(15).minutes.do(send_latest_instagram_post)

# === Перший запуск ===
send_latest_instagram_post()

logger.info("🚀 Бот запущено і працює!")

while True:
    schedule.run_pending()
    time.sleep(10)
