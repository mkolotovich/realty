"""
Запустите: python diagnose4.py
Показывает как упоминаются нужные кварталы в реальных объявлениях.
"""
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "ru-RU,ru;q=0.9"}
SEARCH_TERMS = ["южн", "косиор", "сталинград", "герой"]

for page in range(1, 6):
    url = f"https://incom-lnr.ru/kupit-dom-v-luganske/" + (f"?page={page}" if page > 1 else "")
    r = requests.get(url, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(r.text, "lxml")
    for w in soup.select(".item.h-100"):
        w.decompose()
    for card in soup.select(".product-thumb"):
        link = card.select_one(".product-name a")
        desc_el = card.select_one(".product-description")
        if not link:
            continue
        title = link.get_text(strip=True)
        desc  = desc_el.get_text(separator=" ", strip=True) if desc_el else ""
        full  = (title + " " + desc).lower()
        if any(t in full for t in SEARCH_TERMS):
            print(f"TITLE: {title}")
            print(f"DESC:  {desc[:150]}")
            print()
    if not soup.select_one(f"a[href*='?page={page+1}']"):
        break
print("Готово")
