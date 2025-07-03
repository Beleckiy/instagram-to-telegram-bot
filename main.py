import os
import time
import logging
import schedule
import instaloader
import threading
import http.server
import socketserver
from datetime import datetime

from telegram import Bot
from telegram.error import TelegramError

# === Налаштування логування ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# === Keep-alive сервер ===
def keep_alive():
    PORT = 8080
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        logger.info(f"🌐 Keep-alive сервер працює на порту {PORT}")
        httpd.serve_forever()

threading.Thread(target=keep_alive, daemon=True).start()

# === Змінні середовища ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INSTAGRAM_TARGET = os.getenv("INSTAGRAM_TARGET_USERNAME")
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
INSTAGRAM_SESSIONID = os.getenv("INSTAGRAM_SESSIONID")

# === Ініціалізація бота ===
bot = Bot(token=TELEGRAM_TOKEN)

# === Кеш останнього поста ===
CACHE_FILE = "last_post.txt"

def get_last_post():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return f.read().strip()
    return None

def save_last_post(post_id):
    with open(CACHE_FILE, "w") as f:
        f.write(str(post_id))

# === Instagram клієнт ===
def get_instagram_client():
    L = instaloader.Instaloader(
        sleep=True,
        quiet=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
    
    # Авторизація через sessionid або логін/пароль
    if INSTAGRAM_SESSIONID:
        try:
            L.context._session.cookies.set("sessionid", INSTAGRAM_SESSIONID, domain=".instagram.com")
            L.test_login()
            logger.info("🔑 Успішний вхід через sessionid")
            return L
        except Exception as e:
            logger.error(f"❌ Помилка входу через sessionid: {e}")
    
    if INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD:
        try:
            L.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            logger.info("🔑 Успішний вхід через логін/пароль")
            return L
        except Exception as e:
            logger.error(f"❌ Помилка входу в Instagram: {e}")
            raise
    
    logger.warning("⚠️ Не вказано облікові дані Instagram. Використовується анонімний доступ.")
    return L

# === Основна логіка ===
def check_and_send_post():
    logger.info("🔍 Перевіряємо нові пости...")
    try:
        L = get_instagram_client()
        profile = instaloader.Profile.from_username(L.context, INSTAGRAM_TARGET)
        
        # Отримуємо останній пост
        posts = profile.get_posts()
        latest_post = next(posts)
        
        # Перевіряємо, чи це новий пост
        last_post_id = get_last_post()
        if last_post_id == str(latest_post.shortcode):
            logger.info("⏩ Нових постів не знайдено")
            return
            
        # Завантажуємо медіа
        post_dir = f"temp_{latest_post.shortcode}"
        os.makedirs(post_dir, exist_ok=True)
        L.download_post(latest_post, target=post_dir)
        
        # Знаходимо медіафайл
        media_file = None
        for file in os.listdir(post_dir):
            if file.endswith(('.jpg', '.jpeg', '.png', '.mp4')):
                media_file = os.path.join(post_dir, file)
                break
        
        # Відправляємо в Telegram
        caption = f"\n{latest_post.caption or ''}"
        
        if media_file:
            with open(media_file, 'rb') as media:
                if media_file.endswith(('.mp4', '.mov')):
                    bot.send_video(chat_id=CHAT_ID, video=media, caption=caption)
                else:
                    bot.send_photo(chat_id=CHAT_ID, photo=media, caption=caption)
            logger.info(f"✅ Відправлено новий пост: {latest_post.shortcode}")
        else:
            post_url = f"https://instagram.com/p/{latest_post.shortcode}"
            bot.send_message(chat_id=CHAT_ID, text=f"{caption}\n\n{post_url}")
            logger.warning("⚠️ Не вдалося завантажити медіа, відправлено лише посилання")
        
        # Оновлюємо кеш
        save_last_post(latest_post.shortcode)
        
        # Прибираємо тимчасові файли
        for file in os.listdir(post_dir):
            os.remove(os.path.join(post_dir, file))
        os.rmdir(post_dir)
        
    except instaloader.exceptions.QueryReturnedBadRequestException as e:
        logger.error(f"🚫 Помилка запиту до Instagram: {e}")
        time.sleep(300)  # Затримка при обмеженні запитів
    except Exception as e:
        logger.error(f"❌ Критична помилка: {str(e)}", exc_info=True)

# === Розклад ===
schedule.every(30).minutes.do(check_and_send_post)

# === Запуск ===
if __name__ == "__main__":
    logger.info("🚀 Бот запускається...")
    check_and_send_post()  # Перший запуск
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(10)
        except KeyboardInterrupt:
            logger.info("🛑 Бот зупинено")
            break
        except Exception as e:
            logger.error(f"⚠️ Помилка в головному циклі: {e}")
            time.sleep(60)
