"""
Диагностический скрипт — запустите его у себя и пришлите вывод.
Он покажет реальную HTML-структуру сайта incom-lnr.ru и ответ VK API.

Запуск:
    python diagnose.py
"""
import requests
from bs4 import BeautifulSoup
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

print("=" * 60)
print("1. INCOM-LNR.RU — структура страницы")
print("=" * 60)

try:
    r = requests.get("https://incom-lnr.ru/kupit-dom-v-luganske/", headers=HEADERS, timeout=20)
    print(f"HTTP статус: {r.status_code}")

    soup = BeautifulSoup(r.text, "lxml")

    # Все уникальные классы на странице
    all_classes = set()
    for tag in soup.find_all(True):
        for c in tag.get("class", []):
            all_classes.add(c)

    relevant = sorted(c for c in all_classes if any(k in c.lower() for k in [
        "listing", "property", "item", "card", "post", "article",
        "price", "title", "address", "location", "area", "room",
        "thumb", "image", "img", "detail", "meta", "amenity"
    ]))
    print(f"\nВсего классов на странице: {len(all_classes)}")
    print(f"Релевантные классы ({len(relevant)}):")
    for c in relevant:
        print(f"  .{c}")

    # Первые 3 тега article или div с классом listing/property/item
    print("\n--- Первые карточки объявлений (raw HTML) ---")
    for sel in [".listing-item", "article", ".property", ".item", ".card", ".houzez-listing"]:
        cards = soup.select(sel)
        if cards:
            print(f"\nСелектор '{sel}' нашёл {len(cards)} элементов")
            print("Первый элемент (первые 800 символов):")
            print(str(cards[0])[:800])
            print("...")
            break

    # Title тег страницы
    print(f"\nTitle страницы: {soup.title.string if soup.title else 'нет'}")

    # Ищем любые ссылки на объявления
    links = [a["href"] for a in soup.select("a[href]") if "dom" in a.get("href","") or "property" in a.get("href","") or "listing" in a.get("href","")]
    print(f"\nСсылки похожие на объявления: {links[:5]}")

    # Сохраним кусок HTML для анализа
    with open("incom_page.html", "w", encoding="utf-8") as f:
        f.write(r.text)
    print("\n✓ Полный HTML сохранён в incom_page.html")

except Exception as e:
    print(f"ОШИБКА: {e}")

print("\n" + "=" * 60)
print("2. VK API — тест запроса к стене группы")
print("=" * 60)

try:
    r2 = requests.get(
        "https://api.vk.com/method/wall.get",
        params={"owner_id": "-190575575", "count": "3", "v": "5.131"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    print(f"HTTP статус: {r2.status_code}")
    data = r2.json()
    if "error" in data:
        print(f"VK API ошибка: {data['error']}")
    else:
        items = data.get("response", {}).get("items", [])
        print(f"Получено постов: {len(items)}")
        if items:
            print(f"Первый пост (текст): {items[0].get('text','')[:200]}")
            print(f"Вложения: {[a.get('type') for a in items[0].get('attachments',[])]}")

    with open("vk_response.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("\n✓ Ответ VK сохранён в vk_response.json")

except Exception as e:
    print(f"ОШИБКА: {e}")

print("\nГотово! Пришлите весь вывод этого скрипта.")
