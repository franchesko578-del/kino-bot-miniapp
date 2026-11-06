"""Rangli tugmalar.

Telegram Bot API faqat 3 ta rasmiy rangni qo'llaydi: primary (ko'k),
success (yashil), danger (qizil). Sariq va qora uchun rasmiy rang yo'q,
shuning uchun ularga 🟨 / ⬛ belgisi qo'yiladi.
"""
import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

STYLE = {"blue": "primary", "green": "success", "red": "danger"}
SQUARE = {"yellow": "🟨 ", "black": "⬛ "}

COLOR_ALIASES = {
    "ko'k": "blue", "kok": "blue", "ko‘k": "blue", "blue": "blue",
    "yashil": "green", "green": "green",
    "sariq": "yellow", "yellow": "yellow",
    "qora": "black", "black": "black",
    "qizil": "red", "red": "red",
}


def B(text: str, color: str | None = None, **kw) -> InlineKeyboardButton:
    if color in STYLE:
        kw["style"] = STYLE[color]
    elif color in SQUARE:
        text = SQUARE[color] + text
    return InlineKeyboardButton(text=text, **kw)


def kb(*rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def back(cb: str = "adm:home", text: str = "◀️ Orqaga") -> list:
    return [B(text, "black", callback_data=cb)]


def webapp_btn(text: str, url: str, color: str = "blue") -> InlineKeyboardButton:
    return B(text, color, web_app=WebAppInfo(url=url))


def parse_buttons(text: str) -> InlineKeyboardMarkup | None:
    """Har qator: `Matn | https://havola | rang`. Rang: ko'k/yashil/sariq/qora/qizil."""
    rows = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0]:
            continue
        url = parts[1]
        if not re.match(r"^(https?://|tg://)", url):
            if url.startswith("@"):
                url = "https://t.me/" + url[1:]
            else:
                raise ValueError(f"Havola noto'g'ri: {url}")
        color = COLOR_ALIASES.get(parts[2].lower(), "blue") if len(parts) > 2 else "blue"
        rows.append([B(parts[0], color, url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
