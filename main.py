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
import random
from urllib.parse import urlparse

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
PROXY_URL = os.getenv("PROXY_URL")  # Формат: http://user:pass@host:port

# === Ініціалізація бота ===
bot = Bot(token=TELEGRAM_TOKEN)

# === Кеш постів ===
POSTS_CACHE_FILE = "posts_cache.json"
CURRENT_INDEX_FILE = "current_index.txt"
LAST_CHECK_FILE = "last_check.txt"
FAILED_POSTS_FILE = "failed_posts.txt"
PROXY_ROTATION_FILE = "proxy_rotation.txt"

# === Проксі-сервери ===
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.current_proxy_index = 0
        self.load_proxies()

    def load_proxies(self):
        if PROXY_URL:
            self.proxies = [PROXY_URL]
        # Можна додати додаткові проксі вручну:
        # self.proxies.extend([
        #     'http://proxy1:port',
        #     'http://proxy2:port'
        # ])
        self.load_rotation_state()

    def get_current_proxy(self):
        if not self.proxies:
            return None
        return self.proxies[self.current_proxy_index]

    def rotate_proxy(self):
        if len(self.proxies) > 1:
            self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
            self.save_rotation_state()
            logger.info(f"↻ Ротація проксі. Нове проксі: {self.current_proxy_index+1}/{len(self.proxies)}")
            return self.get_current_proxy()
        return None

    def load_rotation_state(self):
        try:
            with open(PROXY_ROTATION_FILE, 'r') as f:
                self.current_proxy_index = int(f.read().strip())
        except (FileNotFoundError, ValueError):
            self.current_proxy_index = 0

    def save_rotation_state(self):
        with open(PROXY_ROTATION_FILE, 'w') as f:
            f.write(str(self.current_proxy_index))

proxy_manager = ProxyManager()

# === Допоміжні функції ===
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

def add_failed_post(shortcode):
    with open(FAILED_POSTS_FILE, 'a') as f:
        f.write(f"{shortcode}\n")

def get_failed_posts():
    if os.path.exists(FAILED_POSTS_FILE):
        with open(FAILED_POSTS_FILE, 'r') as f:
            return set(f.read().splitlines())
    return set()

# === Instagram клієнт ===
def get_instagram_client():
    proxy = proxy_manager.get_current_proxy()
    
    L = instaloader.Instaloader(
        sleep=True,
        quiet=True,
        request_timeout=120,
        max_connection_attempts=3,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
    
    if proxy:
        parsed = urlparse(proxy)
        proxy_dict = {
            'http': proxy,
            'https': proxy
        }
        L.context._session.proxies.update(proxy_dict)
        logger.info(f"🔌 Використовується проксі: {parsed.hostname}")
    
    if INSTAGRAM_SESSIONID:
        try:
            L.context._session.cookies.set("sessionid", INSTAGRAM_SESSIONID, domain=".instagram.com")
            L.context._session.headers.update({
                'Accept-Language': 'en-US,en;q=0.9',
                'X-IG-App-ID': '936619743392459',
                'X-Requested-With': 'XMLHttpRequest'
            })
            L.test_login()
            logger.info("🔑 Успішний вхід через sessionid")
            return L
        except Exception as e:
            logger.error(f"❌ Помилка входу через sessionid: {e}")
            proxy_manager.rotate_proxy()
    
    if INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD:
        try:
            L.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            logger.info("🔑 Успішний вхід через логін/пароль")
            return L
        except Exception as e:
            logger.error(f"❌ Помилка входу в Instagram: {e}")
            proxy_manager.rotate_proxy()
            raise
    
    logger.warning("⚠️ Не вказано облікові дані Instagram. Використовується анонімний доступ.")
    return L

def get_all_posts_with_retry(max_posts=100):
    """Отримує всі пости з повторними спробами та паузами"""
    attempts = 0
    max_attempts = 3
    posts = []
    
    while attempts < max_attempts:
        try:
            L = get_instagram_client()
            profile = instaloader.Profile.from_username(L.context, INSTAGRAM_TARGET)
            
            for i, post in enumerate(profile.get_posts()):
                posts.append(post)
                
                # Випадкова пауза кожні 3-7 постів
                if i > 0 and i % random.randint(3, 7) == 0:
                    pause = random.randint(15, 45)
                    logger.info(f"⏸ Пауза {pause} сек. (знайдено {len(posts)} постів)")
                    time.sleep(pause)
                
                if len(posts) >= max_posts:
                    break
            
            logger.info(f"📊 Знайдено {len(posts)} постів")
            return posts[::-1]  # Сортуємо від старого до нового
            
        except Exception as e:
            attempts += 1
            error_delay = random.randint(60, 180)
            logger.error(f"❌ Помилка ({attempts}/{max_attempts}): {e}. Спробуємо знову через {error_delay//60} хв.")
            proxy_manager.rotate_proxy()
            time.sleep(error_delay)
    
    logger.error("🚨 Не вдалося отримати пости після кількох спроб")
    return None

def send_post(post):
    """Відправляє один пост в Telegram з повторними спробами"""
    max_attempts = 3
    for attempt in range(max_attempts):
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
            caption = f"\n{post.caption or ''}"
            
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
            logger.error(f"❌ Помилка відправки поста (спроба {attempt+1}/{max_attempts}): {e}")
            if attempt < max_attempts - 1:
                retry_delay = random.randint(30, 90)
                time.sleep(retry_delay)
    
    add_failed_post(post.shortcode)
    return False

def check_for_new_posts():
    """Перевіряє наявність нових постів"""
    logger.info("🔍 Перевірка на нові пости...")
    
    try:
        current_posts = load_posts_cache()
        new_posts = get_all_posts_with_retry(50)  # Обмежуємо кількість для перевірки
        
        if not new_posts:
            return False
        
        new_shortcodes = [post.shortcode for post in new_posts]
        
        if not current_posts or new_shortcodes[0] not in current_posts:
            save_posts_cache(new_posts)
            save_current_index(0)
            save_last_check()
            logger.info(f"🔄 Оновлено список постів. Знайдено {len(new_posts)} постів")
            return True
        
        save_last_check()
        return False
        
    except Exception as e:
        logger.error(f"❌ Помилка перевірки нових постів: {e}")
        return False

def scheduled_posting():
    """Виконує заплановану публікацію"""
    try:
        posts = load_posts_cache()
        if not posts:
            logger.warning("⚠️ Немає постів для публікації. Спробую отримати нові...")
            if not check_for_new_posts():
                logger.error("❌ Не вдалося отримати пости")
                return
        
        posts = load_posts_cache()
        current_index = load_current_index()
        failed_posts = get_failed_posts()
        
        # Якщо всі пости опубліковані
        if current_index >= len(posts):
            logger.info("🏁 Всі пости опубліковано. Очікую нові...")
            if check_for_new_posts():
                current_index = 0
                save_current_index(0)
            else:
                return
        
        # Пропускаємо невдалі пости
        while current_index < len(posts) and posts[current_index] in failed_posts:
            logger.warning(f"⏭ Пропускаємо невдалий пост: {posts[current_index]}")
            current_index += 1
            save_current_index(current_index)
        
        # Якщо залишилися пости для публікації
        if current_index < len(posts):
            logger.info(f"📨 Публікація поста {current_index+1}/{len(posts)}")
            L = get_instagram_client()
            post = instaloader.Post.from_shortcode(L.context, posts[current_index])
            
            if send_post(post):
                save_current_index(current_index + 1)
            else:
                logger.error(f"❌ Не вдалося опублікувати пост {posts[current_index]}")
        
    except Exception as e:
        logger.error(f"❌ Критична помилка в scheduled_posting: {e}")

# Налаштовуємо розклад
schedule.every().day.at("09:00").do(scheduled_posting)
schedule.every().day.at("15:00").do(scheduled_posting)
schedule.every().day.at("21:00").do(scheduled_posting)

# Додаткова перевірка нових постів
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
