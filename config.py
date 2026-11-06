import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}


def _db_url(url: str) -> str:
    # Render/Heroku "postgres://" yoki "postgresql://" beradi, SQLAlchemy async uchun driver kerak
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _db_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///kino.db"))

WEBAPP_URL = (
    os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL") or ""
).strip().rstrip("/")
