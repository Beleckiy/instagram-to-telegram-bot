import os
import time
import logging
from dotenv import load_dotenv
import instaloader
import telegram
from telegram.error import TelegramError
from apscheduler.schedulers.background import BackgroundScheduler

# Завантажуємо змінні з .env
load_dotenv()

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ініціалізація Instaloader
L = instaloader.Instaloader()

try:
    L.login(os.getenv("IG_USERNAME"), os.getenv("IG_PASSWORD"))
    logger.info("✅ Успішний вхід в Instagram")
except Exception as e:
    logger.error(f"❌ Помилка входу в Instagram: {e}")
    exit(1)

# Отримуємо змінні середовища
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")
instagram_username = os.getenv("INSTAGRAM_USERNAME")

# Перевірка токена і чату
if not all([bot_token, chat_id, instagram_username]):
    logger.error("❌ Не всі змінні середовища вказані (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, INSTAGRAM_USERNAME)")
    exit(1)

bot = telegram.Bot(token=bot_token)

# Змінна для збереження ID останнього поста
last_post_shortcode = None

def check_new_post():
    global last_post_shortcode
    try:
        logger.info("🔍 Перевірка наявності нового поста...")

        profile = instaloader.Profile.from_username(L.context, instagram_username)
        posts = profile.get_posts()

        latest_post = next(posts)
        if latest_post.shortcode != last_post_shortcode:
            last_post_shortcode = latest_post.shortcode
            post_url = f"https://www.instagram.com/p/{latest_post.shortcode}/"
            caption = latest_post.caption or "(без підпису)"

            message = f"🆕 Новий пост від @{instagram_username}:\n{caption}\n\n{post_url}"

            bot.send_message(chat_id=chat_id, text=message)
            logger.info("✅ Новий пост відправлено в Telegram")

        else:
            logger.info("ℹ️ Нових постів немає.")
    except TelegramError as te:
        logger.error(f"❌ Telegram помилка: {te}")
    except Exception as e:
        logger.error(f"❌ Інша помилка: {e}")

if __name__ == "__main__":
    logger.info("🚀 Бот запущено і працює!")

    scheduler = BackgroundScheduler()
    scheduler.add_job(check_new_post, 'interval', minutes=5)
    scheduler.start()

    # Перша перевірка одразу після старту
    check_new_post()

    # Keep the bot running
    while True:
        time.sleep(60)
