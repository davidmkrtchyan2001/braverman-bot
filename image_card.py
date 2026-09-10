# -*- coding: utf-8 -*-
"""
Генерация PNG-карточки результата теста Бравермана — формата сторис
(1080x1920), чтобы пользователь мог сохранить и запостить в Instagram/
Telegram-сторис. Это и есть виральный крючок бота: за карточкой видно
подпись/username бота, по которой приходят новые люди.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFont

from test_data import CATEGORIES, CATEGORY_SHORT, status_for

W, H = 1080, 1920

BG_TOP = (18, 14, 38)
BG_BOTTOM = (8, 8, 20)
CARD_BG = (255, 255, 255, 18)
WHITE = (255, 255, 255)
MUTED = (190, 185, 210)

CATEGORY_COLOR = {
    "dopamine": (255, 149, 68),     # оранжевый — энергия
    "acetylcholine": (86, 176, 255),  # синий — ясность
    "gaba": (108, 224, 150),        # зелёный — спокойствие
    "serotonin": (255, 205, 90),    # жёлтый/золотой — настроение/солнце
}

# Шрифт с поддержкой кириллицы лежит прямо в репозитории (fonts/) —
# так он гарантированно доступен на любом хостинге (Railway и т.п.),
# без зависимости от того, что установлено в системе. Системные пути
# оставлены как запасной вариант для локальной разработки.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REGULAR_CANDIDATES = [
    os.path.join(_THIS_DIR, "fonts", "PTSans-Regular.ttf"),
    os.path.join(_THIS_DIR, "PTSans-Regular.ttf"),  # на случай, если папка "расплющилась" при загрузке
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]
_BOLD_CANDIDATES = [
    os.path.join(_THIS_DIR, "fonts", "PTSans-Bold.ttf"),
    os.path.join(_THIS_DIR, "PTSans-Bold.ttf"),
    r"C:\Windows\Fonts\segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def _first_existing(paths: list[str]) -> str | None:
    for p in paths:
        if os.path.exists(p):
            return p
    return None


_REGULAR_PATH = _first_existing(_REGULAR_CANDIDATES)
_BOLD_PATH = _first_existing(_BOLD_CANDIDATES) or _REGULAR_PATH


def _font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


F_TITLE = _font(_BOLD_PATH, 64)
F_SUBTITLE = _font(_REGULAR_PATH, 34)
F_CATEGORY = _font(_BOLD_PATH, 40)
F_PCT = _font(_BOLD_PATH, 44)
F_STATUS = _font(_REGULAR_PATH, 30)
F_FOOTER = _font(_BOLD_PATH, 36)
F_FOOTER_SMALL = _font(_REGULAR_PATH, 28)
F_HINT = _font(_REGULAR_PATH, 24)


def _vertical_gradient(size, top, bottom):
    w, h = size
    base = Image.new("RGB", (1, h), color=0)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = round(top[0] + (bottom[0] - top[0]) * t)
        g = round(top[1] + (bottom[1] - top[1]) * t)
        b = round(top[2] + (bottom[2] - top[2]) * t)
        base.putpixel((0, y), (r, g, b))
    return base.resize((w, h))


def _rounded_bar(draw, x, y, w, h, pct, color, track_color=(255, 255, 255, 30)):
    radius = h // 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=track_color)
    fill_w = max(h, round(w * pct / 100))
    draw.rounded_rectangle([x, y, x + fill_w, y + h], radius=radius, fill=color)


def generate_result_image(percentages: dict, bot_username: str) -> bytes:
    img = _vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # заголовок
    title = "ТЕСТ БРАВЕРМАНА"
    draw.text((W / 2, 140), title, font=F_TITLE, fill=WHITE, anchor="mm")
    subtitle = "Мой профиль нейромедиаторов"
    draw.text((W / 2, 210), subtitle, font=F_SUBTITLE, fill=MUTED, anchor="mm")
    hint = "Чем МЕНЬШЕ % — тем лучше (меньше признаков нехватки)"
    draw.text((W / 2, 254), hint, font=F_HINT, fill=MUTED, anchor="mm")

    # карточка-подложка
    card_x0, card_y0 = 70, 320
    card_x1, card_y1 = W - 70, 320 + 1150
    draw.rounded_rectangle(
        [card_x0, card_y0, card_x1, card_y1], radius=48, fill=(255, 255, 255, 22)
    )

    bar_x = card_x0 + 60
    bar_w = (card_x1 - card_x0) - 120
    bar_h = 34
    row_gap = 270
    y = card_y0 + 90

    for cat in CATEGORIES:
        pct = percentages[cat]
        color = CATEGORY_COLOR[cat]
        name = CATEGORY_SHORT[cat]
        _, status_label = status_for(pct)

        draw.text((bar_x, y), name, font=F_CATEGORY, fill=WHITE)
        draw.text(
            (card_x1 - 60, y), f"{pct}%", font=F_PCT, fill=color, anchor="ra"
        )

        bar_y = y + 70
        _rounded_bar(draw, bar_x, bar_y, bar_w, bar_h, pct, color + (255,))

        draw.text(
            (bar_x, bar_y + 55),
            status_label,
            font=F_STATUS,
            fill=MUTED,
        )

        y += row_gap

    # футер / вотермарка с юзернеймом бота — источник виральности
    footer_y = card_y1 + 90
    draw.text(
        (W / 2, footer_y),
        "Пройди тест бесплатно в Telegram:",
        font=F_FOOTER_SMALL,
        fill=MUTED,
        anchor="mm",
    )
    draw.text(
        (W / 2, footer_y + 55),
        f"@{bot_username}",
        font=F_FOOTER,
        fill=WHITE,
        anchor="mm",
    )

    result = Image.alpha_composite(img, overlay).convert("RGB")

    buf = io.BytesIO()
    result.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()
