import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///kino.db"
)

WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
