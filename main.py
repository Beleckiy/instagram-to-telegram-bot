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
from dotenv import load_dotenv

# Запускаємо псевдосервер на 8080, щоб Render не завершував сервіс
def keep_alive():
    PORT = 8080
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"🌐 Псевдосервер працює на порту {PORT}")
        httpd.serve_forever()

threading.Thread(target=keep_alive, daemon=True).start()

# Завантажуємо змінні оточення
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
)
logger = logging.getLogger()

# Ініціалізуємо Telegram-бота
bot = Bot(token=TELEGRAM_TOKEN)

# Кеш-файл для останнього shortcode посту
CACHE_FILE = "last_shortcode.txt"

def load_last_shortcode():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return f.read().strip()
    return ""

def save_last_shortcode(shortcode):
    with open(CACHE_FILE, "w") as f:
        f.write(shortcode)

# Основна логіка публікації
def send_latest_instagram_post():
    logger.info("🔍 Перевірка наявності нового поста...")
    try:
        loader = instaloader.Instaloader()
        profile = instaloader.Profile.from_username(loader.context, INSTAGRAM_USERNAME)
        posts = profile.get_posts()
        latest_post = next(posts)
        latest_shortcode = latest_post.shortcode

        last_sent = load_last_shortcode()
        if latest_shortcode == last_sent:
            logger.info("⏸ Нових постів немає.")
            return

        post_url = f"https://www.instagram.com/p/{latest_shortcode}/"
        bot.send_message(chat_id=CHAT_ID, text=f"📸 Новий пост в Instagram:\n{post_url}")
        save_last_shortcode(latest_shortcode)
        logger.info(f"✅ Відправлено в Telegram: {post_url}")

    except TelegramError as e:
        logger.error(f"❌ Telegram error: {e}")
    except Exception as e:
        logger.error(f"❌ Інша помилка: {e}")

# Планувальник
schedule.every(15).minutes.do(send_latest_instagram_post)

# Перший запуск одразу
send_latest_instagram_post()

logger.info("🚀 Бот запущено і працює!")

while True:
    schedule.run_pending()
    time.sleep(10)
