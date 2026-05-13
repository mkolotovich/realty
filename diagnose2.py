"""
Запустите: python diagnose2.py
Покажет полный HTML одной карточки и структуру цены/площади.
"""
from bs4 import BeautifulSoup

html = open("incom_page.html", encoding="utf-8").read()
soup = BeautifulSoup(html, "lxml")

items = soup.select(".item")
print(f"Всего .item на странице: {len(items)}\n")

for i, item in enumerate(items):
    print(f"{'='*60}")
    print(f"КАРТОЧКА #{i+1}")
    print(f"{'='*60}")
    print(item.prettify()[:2000])
    print()

# Пагинация
print("\n--- ПАГИНАЦИЯ ---")
for a in soup.select("a"):
    href = a.get("href","")
    text = a.get_text(strip=True)
    if any(k in href for k in ["page=","p=","page/","/2","/3"]) or text in ["Следующая","›","»","2","3","Next"]:
        print(f"  text='{text}' href='{href}'")
