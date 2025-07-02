import os
import time
import instaloader
import schedule
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 3600))
STORIES_INTERVAL = int(os.getenv("STORIES_INTERVAL", 300))
POST_SCHEDULE = os.getenv("POST_SCHEDULE", None)
SEEN_POSTS_FILE = "seen_posts.txt"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
loader = instaloader.Instaloader(dirname_pattern="download", save_metadata=False)

def send_media(media_path, caption=""):
    if media_path.endswith(".jpg"):
        bot.send_photo(chat_id=CHANNEL_USERNAME, photo=open(media_path, "rb"), caption=caption)
    elif media_path.endswith(".mp4"):
        bot.send_video(chat_id=CHANNEL_USERNAME, video=open(media_path, "rb"), caption=caption)

def load_seen_posts():
    if not os.path.exists(SEEN_POSTS_FILE):
        return set()
    with open(SEEN_POSTS_FILE, "r") as f:
        return set(f.read().splitlines())

def save_seen_post(shortcode):
    with open(SEEN_POSTS_FILE, "a") as f:
        f.write(shortcode + "\n")

def check_new_posts():
    seen = load_seen_posts()
    profile = instaloader.Profile.from_username(loader.context, INSTAGRAM_USERNAME)
    for post in profile.get_posts():
        if post.shortcode in seen:
            break
        loader.download_post(post, target="download")
        for file in os.listdir("download"):
            if file.endswith((".jpg", ".mp4")):
                send_media(f"download/{file}", post.caption[:1024] if post.caption else "")
                os.remove(f"download/{file}")
        save_seen_post(post.shortcode)

def check_stories():
    try:
        profile = instaloader.Profile.from_username(loader.context, INSTAGRAM_USERNAME)
        for story in loader.get_stories(userids=[profile.userid]):
            for item in story.get_items():
                loader.download_storyitem(item, target="download")
                for file in os.listdir("download"):
                    if file.endswith((".jpg", ".mp4")):
                        send_media(f"download/{file}", "📺 Story")
                        os.remove(f"download/{file}")
    except Exception as e:
        print(f"[ERROR] Story check failed: {e}")

if POST_SCHEDULE:
    schedule.every().day.at(POST_SCHEDULE).do(check_new_posts)
else:
    schedule.every(CHECK_INTERVAL).seconds.do(check_new_posts)

schedule.every(STORIES_INTERVAL).seconds.do(check_stories)

print("[INFO] Bot started...")
while True:
    schedule.run_pending()
    time.sleep(5)
