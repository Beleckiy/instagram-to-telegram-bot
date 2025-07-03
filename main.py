import os
import time
import logging
import schedule
import instaloader
import threading
import http.server
import socketserver
from datetime import datetime, time as dt_time
import json

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

# === Кеш постів ===
POSTS_CACHE_FILE = "posts_cache.json"
CURRENT_INDEX_FILE = "current_index.txt"
LAST_CHECK_FILE = "last_check.txt"

def save_posts_cache(posts_data):
    with open(POSTS_CACHE_FILE, 'w') as f:
        json.dump([post.shortcode for post in posts_data], f)

def load_posts_cache():
    if os.path.exists(POSTS_CACHE_FILE):
        with open(POSTS_CACHE_FILE, 'r') as f:
            return json.load(f)
    return None

def save_current_index(index):
    with open(CURRENT_INDEX_FILE, 'w') as f:
        f.write(str(index))

def load_current_index():
    if os.path.exists(CURRENT_INDEX_FILE):
        with open(CURRENT_INDEX_FILE, 'r') as f:
            return int(f.read().strip())
    return 0

def save_last_check():
    with open(LAST_CHECK_FILE, 'w') as f:
        f.write(datetime.now().isoformat())

def load_last_check():
    if os.path.exists(LAST_CHECK_FILE):
        with open(LAST_CHECK_FILE, 'r') as f:
            return datetime.fromisoformat(f.read().strip())
    return None

# === Instagram клієнт ===
def get_instagram_client():
    L = instaloader.Instaloader(
        sleep=True,
        quiet=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
    
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

def get_recent_posts(count=17):
    """Отримує вказану кількість останніх постів"""
    try:
        L = get_instagram_client()
        profile = instaloader.Profile.from_username(L.context, INSTAGRAM_TARGET)
        
        posts = []
        for post in profile.get_posts():
            posts.append(post)
            if len(posts) >= count + 5:  # Беремо трохи більше для страховки
                break
        
        # Відсортовуємо від найстарішого до найновішого
        posts = posts[::-1]
        
        logger.info(f"📊 Знайдено {len(posts)} постів")
        return posts
    
    except Exception as e:
        logger.error(f"❌ Помилка отримання постів: {e}")
        return None

def send_post(post):
    """Відправляє один пост в Telegram"""
    try:
        # Завантажуємо медіа
        post_dir = f"temp_{post.shortcode}"
        os.makedirs(post_dir, exist_ok=True)
        L = get_instagram_client()
        L.download_post(post, target=post_dir)
        
        # Знаходимо медіафайл
        media_file = None
        for file in os.listdir(post_dir):
            if file.endswith(('.jpg', '.jpeg', '.png', '.mp4')):
                media_file = os.path.join(post_dir, file)
                break
        
        # Відправляємо в Telegram
        caption = f"📸 Пост від @{INSTAGRAM_TARGET}\n\n{post.caption or ''}"
        
        if media_file:
            with open(media_file, 'rb') as media:
                if media_file.endswith(('.mp4', '.mov')):
                    bot.send_video(chat_id=CHAT_ID, video=media, caption=caption)
                else:
                    bot.send_photo(chat_id=CHAT_ID, photo=media, caption=caption)
            logger.info(f"✅ Відправлено пост: {post.shortcode}")
        else:
            post_url = f"https://instagram.com/p/{post.shortcode}"
            bot.send_message(chat_id=CHAT_ID, text=f"{caption}\n\n{post_url}")
            logger.warning("⚠️ Не вдалося завантажити медіа, відправлено лише посилання")
        
        # Прибираємо тимчасові файли
        for file in os.listdir(post_dir):
            os.remove(os.path.join(post_dir, file))
        os.rmdir(post_dir)
        
        return True
    
    except Exception as e:
        logger.error(f"❌ Помилка відправки поста: {e}")
        return False

def check_for_new_posts():
    """Перевіряє наявність нових постів і оновлює кеш при необхідності"""
    logger.info("🔍 Перевірка на нові пости...")
    current_posts = load_posts_cache()
    new_posts = get_recent_posts(17)
    
    if not new_posts:
        return False
    
    # Якщо немає збережених постів або знайшли нові пости
    if not current_posts or new_posts[0].shortcode not in current_posts:
        save_posts_cache(new_posts)
        save_current_index(0)
        save_last_check()
        logger.info("🔄 Оновлено список постів для публікації")
        return True
    
    save_last_check()
    return False

def scheduled_posting():
    """Виконує заплановану публікацію одного поста"""
    posts = load_posts_cache()
    if not posts:
        logger.warning("⚠️ Немає постів для публікації. Спробую отримати нові...")
        if not check_for_new_posts():
            logger.error("❌ Не вдалося отримати пости")
            return
    
    posts = load_posts_cache()
    current_index = load_current_index()
    
    if current_index >= len(posts):
        logger.info("🏁 Всі пости опубліковано. Очікую нові...")
        if check_for_new_posts():
            # Якщо знайшли нові пости, починаємо знову
            current_index = 0
            save_current_index(0)
        else:
            return
    
    # Отримуємо актуальний список постів
    actual_posts = get_recent_posts(17)
    if not actual_posts:
        logger.error("❌ Не вдалося отримати актуальні пости")
        return
    
    # Знаходимо наш поточний пост у актуальних
    current_shortcode = posts[current_index]
    post_to_send = None
    
    for post in actual_posts:
        if post.shortcode == current_shortcode:
            post_to_send = post
            break
    
    if post_to_send:
        if send_post(post_to_send):
            save_current_index(current_index + 1)
    else:
        logger.warning(f"⚠️ Пост {current_shortcode} більше не знайдено. Пропускаю...")
        save_current_index(current_index + 1)

# Налаштовуємо розклад
schedule.every().day.at("09:00").do(scheduled_posting)
schedule.every().day.at("15:00").do(scheduled_posting)
schedule.every().day.at("21:00").do(scheduled_posting)

# Додаткова перевірка нових постів раз на день
schedule.every().day.at("08:00").do(check_for_new_posts)

# === Запуск ===
if __name__ == "__main__":
    logger.info("🚀 Бот запускається...")
    
    # Перша ініціалізація постів
    if not load_posts_cache():
        logger.info("🔍 Первинне отримання постів...")
        check_for_new_posts()
    
    # Перевіряємо поточний стан
    posts = load_posts_cache()
    current_index = load_current_index()
    logger.info(f"📌 Поточний стан: {current_index}/{len(posts) if posts else 0} постів")
    
    # Запускаємо розклад
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
