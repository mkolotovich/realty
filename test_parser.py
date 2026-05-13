"""
Запустите: python test_parser.py
Проверяет парсер на сохранённом incom_page.html без обращения к сети.
"""
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup

AREA_RE  = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м²|м2|m2)", re.IGNORECASE)
ROOMS_RE = re.compile(r"(\d)\s*[-–]?\s*(?:к(?:омн)?\.?\b)", re.IGNORECASE)
ROOMS_WORDS = {
    "однокомн": 1, "двухкомн": 2, "трёхкомн": 3, "трехкомн": 3,
    "четырёхкомн": 4, "четырехкомн": 4,
}

html = open("incom_page.html", encoding="utf-8").read()
soup = BeautifulSoup(html, "lxml")

# Удаляем виджет новинок
for widget in soup.select(".item.h-100"):
    widget.decompose()

cards = soup.select(".product-thumb")
print(f"Карточек .product-thumb (без виджета): {len(cards)}\n")

area_min = 70  # фильтр площадь от 70

found = 0
for i, card in enumerate(cards):
    link_el = card.select_one(".product-name a")
    if not link_el:
        continue
    href  = link_el.get("href", "")
    title = link_el.get_text(strip=True)

    price_el = card.select_one("[data-price-no-format]")
    price = int(float(price_el["data-price-no-format"])) if price_el else None

    desc_el = card.select_one(".product-description")
    desc = desc_el.get_text(separator=" ", strip=True) if desc_el else ""
    full_text = title + " " + desc

    m_area = AREA_RE.search(full_text)
    area = float(m_area.group(1).replace(",", ".")) if m_area else None

    m_rooms = ROOMS_RE.search(full_text)
    rooms = int(m_rooms.group(1)) if m_rooms else None

    passes_area = area is None or area >= area_min

    print(f"#{i+1} {'✓' if passes_area else '✗ (площадь)'}")
    print(f"  title: {title}")
    print(f"  href:  {href[25:70]}")
    print(f"  price: {price:,} р." if price else "  price: нет")
    print(f"  area:  {area} м²" if area else "  area:  не найдена в тексте")
    print(f"  rooms: {rooms}")
    print(f"  desc:  {desc[:80]}")
    print()
    if passes_area:
        found += 1

print(f"Итого подходит под фильтр 'площадь >= {area_min}': {found} из {len(cards)}")
