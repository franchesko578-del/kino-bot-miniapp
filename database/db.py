from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint,
    func, inspect, select,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    is_vip = Column(Boolean, default=False)
    vip_until = Column(DateTime, nullable=True)
    banned = Column(Boolean, default=False)    # admin bloklagan
    blocked = Column(Boolean, default=False)   # foydalanuvchi botni bloklagan
    created_at = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime, nullable=True)
    referred_by = Column(BigInteger, nullable=True)  # kim taklif qilgan


class Movie(Base):
    __tablename__ = "movies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    file_id = Column(String(255), nullable=False)
    views = Column(Integer, default=0)
    vip_only = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class MoviePart(Base):
    """Serial/ko'p qismli kino. 1-qism Movie.file_id da, 2 va undan keyingilari shu yerda."""
    __tablename__ = "movie_parts"
    __table_args__ = (UniqueConstraint("movie_id", "number"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    movie_id = Column(Integer, nullable=False, index=True)
    number = Column(Integer, nullable=False)
    file_id = Column(String(255), nullable=False)


class Admin(Base):
    __tablename__ = "admins"
    id = Column(BigInteger, primary_key=True)
    added_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SubscriptionChannel(Base):
    __tablename__ = "subscription_channels"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    invite_link = Column(String(500), nullable=False)
    is_active = Column(Boolean, default=True)


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    stars = Column(Integer, nullable=False)
    days = Column(Integer, nullable=False)
    charge_id = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False, default="")


# ---------- Sozlamalar: kalit -> (standart qiymat, tavsif, tur) ----------
SETTINGS = {
    "bot_name": ("🎬 KINO BOT", "Bot nomi", "text"),
    "welcome_text": ("Kino kodini yuboring yoki Mini App'ni oching.", "Bosh menyu (salomlashuv) matni", "text"),
    "announcement": ("", "E'lon matni (/start va Mini App'da ko'rinadi)", "text"),
    "vip_stars": ("100", "VIP narxi (⭐ Stars)", "int"),
    "vip_days": ("30", "VIP muddati (kun)", "int"),
    "btn_app": ("Mini App", "Tugma matni: Mini App", "text"),
    "btn_top": ("TOP 10", "Tugma matni: TOP 10", "text"),
    "btn_new": ("Yangi kinolar", "Tugma matni: Yangi kinolar", "text"),
    "btn_ref": ("Do'st taklif qilish", "Tugma matni: Do'st taklif qilish", "text"),
    "ref_bonus_days": ("3", "Do'st taklifi: har bir do'st uchun bonus VIP kun (0 = o'chiq)", "int0"),
    "ref_limit": ("20", "Do'st taklifi: bitta odam olishi mumkin bo'lgan maksimal mukofot soni", "int"),
    "autopost": ("1", "Yangi kino kanalga avtomatik e'lon qilinsin (1 yoqilgan / 0 o'chirilgan)", "bool"),
    "post_channel": ("", "E'lon kanali (@kanal yoki -100...; bo'sh = o'chiq). Bot kanalda admin bo'lsin", "chan"),
    "btn_vip": ("VIP", "Tugma matni: VIP", "text"),
    "btn_profile": ("Profil", "Tugma matni: Profil", "text"),
    "btn_share": ("Ulashish", "Tugma matni: Ulashish", "text"),
    "color_primary": ("#2f80ed", "Mini App: asosiy/ko'k rang", "color"),
    "color_green": ("#16a34a", "Mini App: yashil tugma", "color"),
    "color_yellow": ("#eab308", "Mini App: sariq tugma", "color"),
    "color_black": ("#1f2937", "Mini App: qora tugma", "color"),
    "color_bg": ("#0f172a", "Mini App: fon rangi", "color"),
    "color_card": ("#1e293b", "Mini App: karta rangi", "color"),
    "force_sub": ("1", "Majburiy obuna (1 yoqilgan / 0 o'chirilgan)", "bool"),
    "protect_content": ("0", "Kinoni saqlash/uzatishni taqiqlash (1/0)", "bool"),
    "maintenance": ("0", "Texnik ishlar rejimi (1/0)", "bool"),
    "maintenance_text": ("🛠 Hozir texnik ishlar ketmoqda. Birozdan so'ng urinib ko'ring.", "Texnik ishlar matni", "text"),
    "movie_caption": ("🎬 <b>{title}</b>\n🔑 Kod: <code>{code}</code>\n👁 Ko'rishlar: {views}", "Kino izohi ({title} {code} {views})", "text"),
}

_cache: dict[str, str] = {}


def S(key: str) -> str:
    return _cache.get(key, SETTINGS[key][0])


def S_int(key: str) -> int:
    try:
        return int(S(key))
    except ValueError:
        return int(SETTINGS[key][0])


def S_on(key: str) -> bool:
    return S(key).strip() == "1"


def validate_setting(key: str, value: str) -> str:
    """Noto'g'ri bo'lsa ValueError ko'taradi."""
    import re
    if key not in SETTINGS:
        raise ValueError("Noma'lum sozlama")
    kind = SETTINGS[key][2]
    value = value.strip()
    if kind in ("int", "int0"):
        low = 0 if kind == "int0" else 1
        if not value.isdigit() or not (low <= int(value) <= 100000):
            raise ValueError(f"{low} dan 100000 gacha son kiriting")
    elif kind == "bool" and value not in ("0", "1"):
        raise ValueError("Faqat 0 yoki 1")
    elif kind == "color" and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Rang #RRGGBB ko'rinishida bo'lsin, masalan #2f80ed")
    elif kind == "chan":
        if value in ("-", "0"):  # o'chirish
            return ""
        if not re.fullmatch(r"(@[A-Za-z0-9_]{4,}|-?\d{6,})", value):
            raise ValueError("@kanal_nomi yoki -100... ID kiriting (tozalash uchun: -)")
    elif len(value) > 3000:
        raise ValueError("Matn juda uzun")
    return value


async def load_settings():
    async with SessionLocal() as s:
        rows = (await s.execute(select(Setting))).scalars().all()
    _cache.clear()
    _cache.update({r.key: r.value for r in rows})


async def set_setting(key: str, value: str):
    value = validate_setting(key, value)
    async with SessionLocal() as s:
        row = await s.get(Setting, key)
        if row:
            row.value = value
        else:
            s.add(Setting(key=key, value=value))
        await s.commit()
    _cache[key] = value


def _add_missing_columns(conn):
    """Eski bazaga yangi ustunlarni avtomatik qo'shadi (create_all buni qilmaydi)."""
    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(conn.dialect)}'
            d = col.default.arg if col.default is not None and col.default.is_scalar else None
            if isinstance(d, bool):
                ddl += " DEFAULT TRUE" if d else " DEFAULT FALSE"
            elif isinstance(d, int):
                ddl += f" DEFAULT {d}"
            conn.exec_driver_sql(ddl)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
    await load_settings()
