"""
Парсер incom-lnr.ru — агентство недвижимости Луганск/ЛНР.
"""
import re
from typing import List, Dict, Optional
from .base import BaseParser

# Версия файла — для диагностики
PARSER_VERSION = "4.0"

URL_SEGMENTS = {
    ("sale",  "apartment"): "kupit-kvartiru-v-luganske",
    ("sale",  "house"):     "kupit-dom-v-luganske",
    ("sale",  "commercial"):"kupit-kommercheskuyu-nedvizhimost-v-luganske",
    ("rent",  "apartment"): "arenda-kvartir-v-luganske",
    ("rent",  "house"):     "arenda-domov-v-luganske",
    ("rent",  "commercial"):"arenda-kommercheskoy-nedvizhimosti-v-luganske",
}

ROOMS_WORDS = {
    "однокомн": 1, "двухкомн": 2, "трёхкомн": 3, "трехкомн": 3,
    "четырёхкомн": 4, "четырехкомн": 4,
}

PLOT_KEYWORDS = [
    "участок", "земельный", "земля", "огород", "дача", "садовый",
    "снт ", " снт", "сот.", "соток", "гектар",
]

NOT_LUGANSK_KEYWORDS = [
    "старый айдар", "новый айдар", "николаевк", "степановк", "видн",
    "краснодон", "свердловск", "ровеньки", "антрацит", "брянка",
    "алчевск", "стаханов", "перевальск", "кировск", "красный луч",
    "лутугино", "троицкое", "беловодск", "марковка", "новопсков",
    "запорожск", "азовск", "черном", "крым",
]

LUGANSK_KEYWORDS = [
    "луганск", "лнр", "г. луганск", "г.луганск", "город луганск",
    "ленинский район", "жовтневый район", "артемовский район",
    "каменнобродский район", "центр", "центральный",
]

# Расположения: ключ = значение чекбокса в UI
# Значения нормализуются через _normalize_text перед сравнением.
DISTRICTS: dict = {
    "южн": [
        "южн", "южный", "кв южн", "квартал южн", "р н кв южн",
    ],
    "косиор": [
        "косиор", "пос косиор", "поселок косиор",
    ],
    "сталинград": [
        "сталинград", "героев сталинград", "кв героев сталинград",
    ],
}


class IncomLnrParser(BaseParser):
    name         = "incom_lnr"
    display_name = "ИНКОМ ЛНР (Луганск)"
    base_url     = "https://incom-lnr.ru"

    AREA_RE  = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м²|м2|m2)", re.IGNORECASE)
    ROOMS_RE = re.compile(r"(\d)\s*[-–]?\s*(?:к(?:омн)?\.?\b)", re.IGNORECASE)
    NON_WORD_RE = re.compile(r"[^0-9a-zа-я]+", re.IGNORECASE)

    def parse(self, filters: Dict) -> List[Dict]:
        deal_type   = filters.get("deal_type", "sale")
        prop_type   = filters.get("property_type", "apartment")
        price_min   = int(filters.get("price_min") or 0)
        price_max   = int(filters.get("price_max") or 999_000_000)
        rooms_f     = filters.get("rooms")
        area_min    = float(filters.get("area_min") or 0)
        area_max    = float(filters.get("area_max") or 99999)
        city_f      = (filters.get("city") or "").strip().lower()
        # districts — список ключей из DISTRICTS, например ["косиор", "южн"]
        # Поддерживаем также location/locations для совместимости.
        districts_f = self._normalize_district_filters(
            filters.get("districts") or filters.get("locations") or filters.get("location")
        )
        filter_city  = "луганск" in city_f
        filter_plots = prop_type == "house"

        print(f"[incom_lnr v{PARSER_VERSION}] filters received: districts={districts_f} city={city_f!r}")

        segment = URL_SEGMENTS.get((deal_type, prop_type))
        if not segment:
            return []

        catalog_url = f"{self.base_url}/{segment}/"
        listings = []
        skipped_district = 0

        for page in range(1, 43):
            url = catalog_url if page == 1 else f"{catalog_url}?page={page}"
            soup = self.get_page(url)
            if soup is None:
                break

            for widget in soup.select(".item.h-100"):
                widget.decompose()

            cards = soup.select(".product-thumb")
            if not cards:
                break

            for card in cards:
                link_el = card.select_one(".product-name a")
                if not link_el:
                    continue
                href  = link_el.get("href", "")
                title = link_el.get_text(strip=True)

                desc_el = card.select_one(".product-description")
                desc = desc_el.get_text(separator=" ", strip=True) if desc_el else ""
                full_text = (title + " " + desc).lower()
                normalized_text = self._normalize_text(full_text)

                if filter_plots and any(kw in full_text for kw in PLOT_KEYWORDS):
                    continue

                if filter_city:
                    has_lug   = any(kw in full_text for kw in LUGANSK_KEYWORDS)
                    has_other = any(kw in full_text for kw in NOT_LUGANSK_KEYWORDS)
                    if has_other and not has_lug:
                        continue

                # ── Фильтр по расположению ─────────────────────────────────
                if districts_f:
                    matched = any(self._district_match(normalized_text, dk) for dk in districts_f)
                    if not matched:
                        skipped_district += 1
                        continue

                image = ""
                img_el = card.select_one(".image img")
                if img_el:
                    image = img_el.get("data-srcset") or img_el.get("src", "")
                    if image and not image.startswith("http"):
                        image = self.base_url + "/" + image.lstrip("/")

                price: Optional[int] = None
                price_el = card.select_one("[data-price-no-format]")
                if price_el:
                    try:
                        price = int(float(price_el["data-price-no-format"]))
                    except (ValueError, TypeError):
                        pass
                if price is None:
                    pf = card.select_one(".price_no_format")
                    if pf:
                        digits = re.sub(r"[^\d]", "", pf.get_text())
                        if digits:
                            price = int(digits)

                area  = self._parse_area(title + " " + desc)
                rooms = self._parse_rooms(title + " " + desc)
                addr  = self._extract_address(title, desc)

                if price is not None and not (price_min <= price <= price_max):
                    continue
                if area is not None and not (area_min <= area <= area_max):
                    continue
                if rooms_f is not None and rooms is not None:
                    if str(rooms) != str(rooms_f):
                        continue

                listings.append(self._listing(
                    title=title, price=price, currency="RUB",
                    area=area, rooms=rooms, address=addr,
                    url=href, image=image,
                ))

            if not soup.select_one(f"a[href*='?page={page + 1}']"):
                break

        print(f"[incom_lnr v{PARSER_VERSION}] done: found={len(listings)} skipped_by_district={skipped_district}")
        return listings

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
        normalized = []
        for val in values:
            norm = self._normalize_text(str(val))
            if norm:
                normalized.append(norm)
        return normalized

    def _district_match(self, normalized_text: str, district_key: str) -> bool:
        district_variants = DISTRICTS.get(district_key, [district_key])
        normalized_variants = [self._normalize_text(v) for v in district_variants]
        return any(variant and variant in normalized_text for variant in normalized_variants)

    def _parse_area(self, text: str) -> Optional[float]:
        m = self.AREA_RE.search(text)
        return float(m.group(1).replace(",", ".")) if m else None

    def _parse_rooms(self, text: str) -> Optional[int]:
        t = text.lower()
        for word, count in ROOMS_WORDS.items():
            if word in t:
                return count
        if "студи" in t:
            return 0
        m = self.ROOMS_RE.search(text)
        return int(m.group(1)) if m else None

    def _extract_address(self, title: str, desc: str) -> str:
        addr = re.sub(
            r"^(продам|сдам|продаётся|сдаётся|аренда)\s*",
            "", title, flags=re.IGNORECASE
        ).strip()
        if len(addr) < 5:
            m = re.search(
                r"(?:ул\.|улица|пр-т|пр\.|квартал|кв\.)\s*[^\n,]{3,40}",
                desc, re.IGNORECASE
            )
            if m:
                addr = m.group(0).strip()
        return addr or "Луганск"
