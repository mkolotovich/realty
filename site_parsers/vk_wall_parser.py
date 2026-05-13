"""
Парсер ВКонтакте — публичная стена сообщества недвижимости.

Использует VK API (открытый метод wall.get, не требует токена для публичных групп).
Группа: vk.com/wall-190575575  (ЛНР/Луганск — продам дом Флигель и др.)

Как это работает:
  - VK API wall.get возвращает JSON с постами
  - Мы ищем посты с хэштегами #ПродамДом, #Продам, #Аренда и т.д.
  - Из текста поста regex-ом извлекаем цену, адрес, площадь
  - Фото берём из первого вложения
"""
import re
import time
import json
from pathlib import Path
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
from .base import BaseParser


# ── Константы ──────────────────────────────────────────────────────────────
VK_API  = "https://api.vk.com/method"
VK_VER  = "5.131"

# ID группы (число после знака минус в wall-190575575)
GROUP_ID = "190575575"

# Хэштеги по типу сделки — используем при фильтрации текста поста
SALE_TAGS = ["#продам", "#продаю", "#продажа", "#продамдом", "#продамквартиру",
             "#продамкоммерческую", "продам", "продаётся", "продается"]
RENT_TAGS = ["#сдам", "#аренда", "#снять", "сдам", "сдаётся", "сдается"]

# Соответствие типа недвижимости → ключевые слова в тексте поста
PROP_KEYWORDS = {
    "apartment": ["квартир", "студи", "апартамент", "комнат"],
    "house":     ["дом", "домик", "коттедж", "дача", "таунхаус", "флигель"],
    "commercial": ["офис", "магазин", "торговый", "склад", "коммерческ", "помещение"],
}

DISTRICT_KEYWORDS = {
    "южн": ["южн", "южный", "кв южн", "квартал южн"],
    "косиор": ["косиор", "косиора", "пос косиор", "поселок косиор"],
    "сталинград": ["сталинград", "героев сталинград", "кв героев сталинград"],
}

# Если в фильтре город «Луганск», отсекаем типичные сёла/посёлки ЛНР без упоминания Луганска.
OUTSIDE_LUGANSK_KEYWORDS = [
    "сабовка", "вергунка", "старый айдар", "новый айдар", "николаевк", "степановк", "видн",
    "краснодон", "свердловск", "ровеньки", "антрацит", "брянка",
    "алчевск", "стаханов", "перевальск", "кировск", "красный луч",
    "лутугино", "троицкое", "беловодск", "марковка", "новопсков",
    "запорожск", "азовск", "черном", "крым",
]

LUGANSK_IN_TEXT_KEYWORDS = [
    "луганск", "г луганск", "г.луганск", "город луганск", "лнр",
    "ленинский район", "жовтневый район", "артемовский район", "артёмовский район",
    "каменнобродский район", "центр", "центральный",
]


class VkWallParser(BaseParser):
    name         = "vk_wall"
    display_name = "VK — wall-190575575"
    base_url     = "https://vk.ru/wall-190575575"

    # Токен читается из локального файла config.local.json
    ACCESS_TOKEN = ""

    SEARCH_URL = f"{VK_API}/wall.search"
    GET_URL    = f"{VK_API}/wall.get"

    # ── Regex для извлечения данных из текста поста ────────────────────────
    # Цена: "3 500 000 руб", "350 000$", "$ 25 000", "25тыс"
    PRICE_RE = re.compile(
        r"(?:цена|стоимость|за|=)?\s*"
        r"([\d\s]{2,12})"
        r"\s*(?:тыс\.?|млн\.?|руб\.?|грн\.?|₽|\$|usd|$)",
        re.IGNORECASE,
    )
    # Площадь: "85 кв.м", "85м²", "площадь 85"
    AREA_RE = re.compile(
        r"(\d{1,4}(?:[.,]\d)?)\s*(?:кв\.?\s*м|м²|м2|кв\s*метр)",
        re.IGNORECASE,
    )
    # Адрес после ключевых слов
    ADDR_RE = re.compile(
        r"(?:адрес|район|улица|ул\.|пр-т|пр\.)\s*[:\-–]?\s*([^\n,\.]{5,60})",
        re.IGNORECASE,
    )
    # Комнаты
    ROOMS_RE = re.compile(
        r"(\d)\s*[-–]?\s*(?:комн|ком\.)",
        re.IGNORECASE,
    )
    NON_WORD_RE = re.compile(r"[^0-9a-zа-я]+", re.IGNORECASE)

    def parse(self, filters: Dict) -> List[Dict]:
        self.ACCESS_TOKEN = self._load_token_from_local_file()
        deal_type  = filters.get("deal_type", "sale")
        prop_type  = filters.get("property_type", "apartment")
        price_min  = int(filters.get("price_min") or 0)
        price_max  = int(filters.get("price_max") or 999_000_000)
        area_min   = float(filters.get("area_min") or 0)
        area_max   = float(filters.get("area_max") or 99999)
        city_f     = (filters.get("city") or "").strip().lower()
        districts_f = self._normalize_district_filters(filters.get("districts"))
        strict_area = area_min > 0 or area_max < 99999

        # 1) Сначала пробуем API (если токен валиден, это самый стабильный путь).
        posts = self._fetch_posts("", count=100)
        # 2) Фолбэки по HTML.
        if not posts:
            posts = self._fetch_posts_public_page(count=80)
        if not posts:
            posts = self._fetch_posts_from_raw_html(count=80)
        if not posts:
            posts = self._fetch_posts_mobile(count=60)

        print(f"[vk_wall] fetched_posts={len(posts)}")
        listings = []
        for post in posts:
            text = (post.get("text") or "").strip()
            if not text and post.get("copy_history"):
                # Многие записи в пабликах — репосты, текст хранится в copy_history.
                text = ((post["copy_history"][0] or {}).get("text") or "").strip()
            if not text:
                continue

            if not self._matches_deal(text, deal_type):
                continue
            if not self._matches_prop_strict(text, prop_type):
                continue
            if districts_f and not self._matches_district(text, districts_f):
                continue
            if not self._matches_city_scope(text, city_f):
                continue

            price = self._extract_price(text)
            if price and not (price_min <= price <= price_max):
                continue

            area  = self._extract_area(text)
            if not self._matches_area(area, area_min, area_max, strict_area):
                continue
            rooms = self._extract_rooms(text)
            addr  = self._extract_addr(text) or filters.get("city", "Луганск")
            image = self._extract_image(post)
            title = self._make_title(text, prop_type, rooms, area)
            post_id = post.get("id")
            url = f"https://vk.ru/wall-{GROUP_ID}_{post_id}" if post_id else self.base_url

            listings.append(self._listing(
                title   = title,
                price   = price,
                currency= "RUB",
                area    = area,
                rooms   = rooms,
                address = addr,
                url     = url,
                image   = image,
            ))

        if not listings:
            # Если получили посты, но не смогли собрать объявления —
            # принудительно строим карточки из сырого HTML.
            raw_posts = self._fetch_posts_from_raw_html(count=30)
            for post in raw_posts:
                text = (post.get("text") or "").strip()
                if not text:
                    continue
                if not self._matches_deal(text, deal_type):
                    continue
                if not self._matches_prop_strict(text, prop_type):
                    continue
                if districts_f and not self._matches_district(text, districts_f):
                    continue
                if not self._matches_city_scope(text, city_f):
                    continue
                area_post = self._extract_area(text)
                if not self._matches_area(area_post, area_min, area_max, strict_area):
                    continue
                post_id = post.get("id")
                listings.append(self._listing(
                    title=self._make_title(text, prop_type, None, None),
                    price=self._extract_price(text),
                    currency="RUB",
                    area=area_post,
                    rooms=self._extract_rooms(text),
                    address=self._extract_addr(text) or filters.get("city", "Луганск"),
                    url=f"https://vk.ru/wall-{GROUP_ID}_{post_id}" if post_id else self.base_url,
                    image=self._extract_image(post),
                ))
                if len(listings) >= 20:
                    break

        if not listings and posts:
            # Крайний fallback: вернём несколько свежих постов как объявления,
            # даже если текст не прошёл эвристики по типу сделки/объекта.
            for post in posts[:20]:
                text = (post.get("text") or "").strip()
                if not text:
                    continue
                if not self._matches_deal(text, deal_type):
                    continue
                if not self._matches_prop_strict(text, prop_type):
                    continue
                if districts_f and not self._matches_district(text, districts_f):
                    continue
                if not self._matches_city_scope(text, city_f):
                    continue
                price = self._extract_price(text)
                if price and not (price_min <= price <= price_max):
                    continue
                area_fb = self._extract_area(text)
                if not self._matches_area(area_fb, area_min, area_max, strict_area):
                    continue
                post_id = post.get("id")
                listings.append(self._listing(
                    title=self._make_title(text, prop_type, None, None),
                    price=price,
                    currency="RUB",
                    area=area_fb,
                    rooms=self._extract_rooms(text),
                    address=self._extract_addr(text) or filters.get("city", "Луганск"),
                    url=f"https://vk.ru/wall-{GROUP_ID}_{post_id}" if post_id else self.base_url,
                    image=self._extract_image(post),
                ))

        if not listings:
            # Последний fail-safe, чтобы источник не был пустым в UI.
            listings.append(self._listing(
                title="VK: по заданным фильтрам ничего не найдено",
                price=None,
                currency="RUB",
                area=None,
                rooms=None,
                address=filters.get("city", "Луганск"),
                url=self.base_url,
                image="",
            ))

        print(f"[vk_wall] done listings={len(listings)} deal={deal_type} prop={prop_type} token={'yes' if self.ACCESS_TOKEN else 'no'}")
        return listings

    # ── VK API ─────────────────────────────────────────────────────────────

    def _fetch_posts(self, query: str, count: int = 100) -> list:
        """Получает посты через wall.search или wall.get."""
        if not self.ACCESS_TOKEN:
            print("[vk_wall] token is empty in config.local.json, skip API")
            return []
        endpoint = self.SEARCH_URL if query else self.GET_URL
        common = {
            "count": min(count, 100),
            "v": VK_VER,
            "access_token": self.ACCESS_TOKEN,
        }
        attempts = []
        if query:
            attempts.append({**common, "owner_id": f"-{GROUP_ID}", "query": query})
            attempts.append({**common, "domain": "nedvizhimost_lugansk_lnr", "query": query})
        else:
            attempts.append({**common, "owner_id": f"-{GROUP_ID}"})
            attempts.append({**common, "domain": "nedvizhimost_lugansk_lnr"})

        for params in attempts:
            try:
                resp = requests.get(
                    endpoint,
                    params=params,
                    timeout=15,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                data = resp.json()
                if data.get("error"):
                    print(f"[vk_wall] API error payload: {data.get('error')} params={ {k:v for k,v in params.items() if k!='access_token'} }")
                    continue
                items = data.get("response", {}).get("items", [])
                if items:
                    return items
            except Exception as e:
                print(f"[vk_wall] API error: {e}")
        return []

    def _load_token_from_local_file(self) -> str:
        """
        Формат файла config.local.json в корне проекта:
        {
          "vk_token": "..."
        }
        """
        try:
            project_root = Path(__file__).resolve().parents[1]
            cfg_path = project_root / "config.local.json"
            if not cfg_path.exists():
                return ""
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            token = str(raw.get("vk_token") or "").strip()
            return token
        except Exception as e:
            print(f"[vk_wall] config read error: {e}")
            return ""

    def _fetch_posts_mobile(self, count: int = 60) -> list:
        """
        Fallback без VK API:
        берём посты с m.vk.com/wall-<group_id>, где текст доступен в HTML.
        """
        url = f"https://m.vk.com/wall-{GROUP_ID}"
        try:
            resp = requests.get(
                url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "lxml")
            posts = []
            for block in soup.select("div[data-post-id], div.wall_item")[:count]:
                raw_id = (block.get("data-post-id") or "").strip()
                text_el = block.select_one(".pi_text, .wall_post_text, .wi_body, .post__text")
                text = text_el.get_text(" ", strip=True) if text_el else ""
                if not text:
                    continue
                vk_id = None
                m = re.search(r"(-?\d+)_(\d+)", raw_id)
                if m:
                    vk_id = int(m.group(2))
                img_el = block.select_one("img")
                image = img_el.get("src", "") if img_el else ""
                posts.append({
                    "id": vk_id,
                    "text": text,
                    "image": image,
                    "attachments": [],
                })
            if len(posts) < 5:
                posts.extend(self._extract_posts_from_text_blob(soup, count=count, skip_existing=posts))
            return posts[:count]
        except Exception as e:
            print(f"[vk_wall] mobile fallback error: {e}")
            return []

    def _fetch_posts_public_page(self, count: int = 60) -> list:
        """
        Fallback через desktop-страницу VK.
        Нужен на случай, когда API недоступен, а m.vk.com отдаёт заглушку.
        """
        try:
            resp = requests.get(
                self.base_url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            posts = []
            seen_ids = set()
            href_re = re.compile(rf"/?wall-{GROUP_ID}_(\d+)")

            for link in soup.find_all("a", href=href_re):
                href = link.get("href", "")
                match = href_re.search(href)
                if not match:
                    continue
                post_id = int(match.group(1))
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                container = link
                # Поднимаемся вверх, чтобы взять текст самого поста.
                for _ in range(6):
                    if container is None:
                        break
                    text = container.get_text(" ", strip=True)
                    if len(text) > 80:
                        break
                    container = container.parent

                if container is None:
                    continue
                text = container.get_text(" ", strip=True)
                if len(text) < 30:
                    continue

                img_el = container.select_one("img")
                image = img_el.get("src", "") if img_el else ""

                posts.append({
                    "id": post_id,
                    "text": text,
                    "image": image,
                    "attachments": [],
                })
                if len(posts) >= count:
                    break

            if len(posts) < 5:
                posts.extend(self._extract_posts_from_text_blob(soup, count=count, skip_existing=posts))
            return posts[:count]
        except Exception as e:
            print(f"[vk_wall] desktop fallback error: {e}")
            return []

    def _fetch_posts_from_raw_html(self, count: int = 60) -> list:
        """
        Крайний fallback: ищем wall-id и текстовые блоки напрямую в HTML.
        Полезно, когда обычные селекторы ничего не отдают.
        """
        try:
            resp = requests.get(
                self.base_url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200 or not resp.text:
                return []
            html = resp.text

            # Пытаемся вытащить JSON-like "text":"...".
            text_candidates = []
            for m in re.finditer(r'"text"\s*:\s*"([^"]{40,5000})"', html):
                txt = m.group(1)
                txt = txt.encode("utf-8", "ignore").decode("unicode_escape", "ignore")
                txt = re.sub(r"<[^>]+>", " ", txt)
                txt = re.sub(r"\s+", " ", txt).strip()
                if len(txt) >= 60:
                    text_candidates.append(txt)
                if len(text_candidates) >= count * 2:
                    break

            # Если JSON-тексты не найдены, режем чистый текст страницы.
            if not text_candidates:
                plain = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
                plain = re.sub(r"<style[\s\S]*?</style>", " ", plain, flags=re.IGNORECASE)
                plain = re.sub(r"<[^>]+>", "\n", plain)
                chunks = re.split(r"(?:Show likes|Share|Leave a comment|Показать лайки|Поделиться)", plain)
                for chunk in chunks:
                    txt = re.sub(r"\s+", " ", chunk).strip()
                    if len(txt) >= 80:
                        text_candidates.append(txt[:2000])
                    if len(text_candidates) >= count * 2:
                        break

            posts = []
            seen = set()
            for txt in text_candidates:
                low = txt.lower()
                if not any(k in low for k in ("продам", "сдам", "аренда", "квартира", "дом", "недвиж")):
                    continue
                if txt in seen:
                    continue
                seen.add(txt)
                m_id = re.search(rf"wall-{GROUP_ID}_(\d+)", txt)
                posts.append({
                    "id": int(m_id.group(1)) if m_id else None,
                    "text": txt,
                    "image": "",
                    "attachments": [],
                })
                if len(posts) >= count:
                    break
            return posts
        except Exception as e:
            print(f"[vk_wall] raw-html fallback error: {e}")
            return []

    def _extract_posts_from_text_blob(self, soup: BeautifulSoup, count: int, skip_existing: list) -> list:
        """
        Текстовый fallback на случай, когда CSS-структура VK изменилась.
        Режем общий текст страницы на смысловые блоки и извлекаем похожие на объявления.
        """
        existing_texts = {(p.get("text") or "").strip() for p in (skip_existing or [])}
        all_text = soup.get_text("\n", strip=True)
        chunks = re.split(r"(?:Show likes|Share|Показать лайки|Поделиться|Leave a comment)", all_text)

        posts = []
        for chunk in chunks:
            text = re.sub(r"\s+", " ", (chunk or "")).strip()
            if len(text) < 80 or len(text) > 4000:
                continue
            tl = text.lower()
            is_realty_like = (
                any(k in tl for k in ("продам", "сдам", "аренда", "квартира", "дом", "комната", "недвиж"))
                or bool(re.search(r"\+7\d{10}", text))
                or bool(re.search(r"\b\d[\d\s]{3,}\s*(?:руб|р|₽)\b", tl))
            )
            if not is_realty_like:
                continue
            if text in existing_texts:
                continue
            existing_texts.add(text)

            # Пытаемся взять id поста из текста блока, если он там есть.
            m = re.search(rf"wall-{GROUP_ID}_(\d+)", text)
            post_id = int(m.group(1)) if m else None
            posts.append({
                "id": post_id,
                "text": text[:2000],
                "image": "",
                "attachments": [],
            })
            if len(posts) >= count:
                break
        return posts

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _build_query(self, deal_type: str, prop_type: str) -> str:
        """Строим поисковую строку для wall.search."""
        deal_word = "продам" if deal_type == "sale" else "сдам"
        prop_words = PROP_KEYWORDS.get(prop_type, ["квартир"])
        return f"{deal_word} {prop_words[0]}"

    def _matches_deal(self, text: str, deal_type: str) -> bool:
        t = text.lower()
        if deal_type == "rent":
            return any(w in t for w in RENT_TAGS)
        # sale — проверяем что это не аренда
        has_sale = any(w in t for w in SALE_TAGS)
        has_rent = any(w in t for w in RENT_TAGS)
        return has_sale or (not has_rent)  # если нет явной аренды — считаем продажей

    def _matches_prop(self, text: str, prop_type: str) -> bool:
        keywords = PROP_KEYWORDS.get(prop_type, [])
        t = text.lower()
        if any(k in t for k in keywords):
            return True
        # Если тип не удалось уверенно определить по тексту,
        # не отбрасываем пост полностью (иначе часто 0 результатов).
        return True

    def _matches_prop_strict(self, text: str, prop_type: str) -> bool:
        t = text.lower()
        house_hits = sum(1 for k in PROP_KEYWORDS["house"] if k in t)
        apt_hits = sum(1 for k in PROP_KEYWORDS["apartment"] if k in t)
        com_hits = sum(1 for k in PROP_KEYWORDS["commercial"] if k in t)

        if prop_type == "house":
            return house_hits > 0 and house_hits >= apt_hits and house_hits >= com_hits
        if prop_type == "apartment":
            return apt_hits > 0 and apt_hits >= house_hits and apt_hits >= com_hits
        if prop_type == "commercial":
            return com_hits > 0 and com_hits >= house_hits and com_hits >= apt_hits
        return False

    def _normalize_text(self, text: str) -> str:
        t = (text or "").lower().replace("ё", "е")
        t = self.NON_WORD_RE.sub(" ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _normalize_district_filters(self, raw_districts) -> List[str]:
        if not raw_districts:
            return []
        if isinstance(raw_districts, str):
            values = [raw_districts]
        elif isinstance(raw_districts, list):
            values = raw_districts
        else:
            return []
        return [self._normalize_text(str(v)) for v in values if str(v).strip()]

    def _matches_district(self, text: str, selected_keys: List[str]) -> bool:
        normalized = self._normalize_text(text)
        for key in selected_keys:
            variants = DISTRICT_KEYWORDS.get(key, [key])
            for variant in variants:
                if self._normalize_text(variant) in normalized:
                    return True
        return False

    SETTLEMENT_PREFIX_RE = re.compile(
        r"(?:^|[\s,.;\n])(?:с\.|село|пос\.|поселок|посёлок)\s*[А-Яа-яЁё]",
        re.IGNORECASE | re.MULTILINE,
    )

    def _matches_city_scope(self, text: str, city_f: str) -> bool:
        """Для города Луганск отбрасываем объявления явно из других НП без упоминания Луганска."""
        cf = (city_f or "").strip().lower()
        if not cf:
            cf = "луганск"
        if "луганск" not in cf:
            return True

        tl = text.lower()
        has_lugansk_hint = any(k in tl for k in LUGANSK_IN_TEXT_KEYWORDS)
        has_outside_place = any(k in tl for k in OUTSIDE_LUGANSK_KEYWORDS)

        if has_outside_place and not has_lugansk_hint:
            return False
        if self.SETTLEMENT_PREFIX_RE.search(text) and not has_lugansk_hint:
            return False
        return True

    def _matches_area(
        self,
        area: Optional[float],
        area_min: float,
        area_max: float,
        strict: bool,
    ) -> bool:
        if area is not None:
            return area_min <= area <= area_max
        return not strict

    def _extract_price(self, text: str):
        # Ищем числа рядом со словами-ценовыми маркерами
        # Упрощённый вариант: берём первое большое число в тексте
        for m in re.finditer(r"\b(\d[\d\s]{2,10}\d)\b", text):
            raw = m.group(1).replace(" ", "").replace("\xa0", "")
            if raw.isdigit():
                val = int(raw)
                # Разумный диапазон цен на недвижимость
                if 10_000 <= val <= 100_000_000:
                    return val
                # "тыс" → умножаем
                ctx = text[max(0, m.end()-2):m.end()+6].lower()
                if "тыс" in ctx and 10 <= val <= 100_000:
                    return val * 1000
                if "млн" in ctx and 1 <= val <= 1_000:
                    return val * 1_000_000
        return None

    def _extract_area(self, text: str):
        m = self.AREA_RE.search(text)
        if m:
            return float(m.group(1).replace(",", "."))
        return None

    def _extract_rooms(self, text: str):
        m = self.ROOMS_RE.search(text)
        if m:
            return int(m.group(1))
        if "студи" in text.lower():
            return 0
        return None

    def _extract_addr(self, text: str):
        m = self.ADDR_RE.search(text)
        return m.group(1).strip() if m else None

    def _extract_image(self, post: dict) -> str:
        """Берём первое фото из вложений поста."""
        if post.get("image"):
            return post.get("image", "")
        for att in post.get("attachments", []):
            if att.get("type") == "photo":
                sizes = att["photo"].get("sizes", [])
                # Берём наибольший размер
                best = max(sizes, key=lambda s: s.get("width", 0), default=None)
                if best:
                    return best.get("url", "")
        return ""

    def _make_title(self, text: str, prop_type: str, rooms, area) -> str:
        """Формируем заголовок из первой строки поста."""
        first_line = text.strip().split("\n")[0][:80]
        return first_line or f"Объявление ({prop_type})"
