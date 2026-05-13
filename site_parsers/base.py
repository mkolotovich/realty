"""
Base parser class. All site parsers must inherit from this.
"""
import requests
from bs4 import BeautifulSoup
from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class BaseParser(ABC):
    """
    Base class for all real estate parsers.
    
    To add a new site, create a new file in /parsers/ and inherit from BaseParser.
    Implement the `parse` method that returns a list of listing dicts.
    """

    name: str = "base"           # Unique identifier for this parser
    display_name: str = "Base"   # Human-readable name shown in UI
    base_url: str = ""           # Root URL of the site

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    def get_page(self, url: str, params: dict = None) -> Optional[BeautifulSoup]:
        try:
            resp = requests.get(url, headers=self.HEADERS, params=params, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception as e:
            print(f"[{self.name}] Error fetching {url}: {e}")
            return None

    @abstractmethod
    def parse(self, filters: Dict) -> List[Dict]:
        """
        Parse listings from the site using given filters.
        
        Expected filter keys (all optional):
          - deal_type: "rent" | "sale"
          - property_type: "apartment" | "house" | "commercial"
          - city: str
          - price_min: int
          - price_max: int
          - rooms: int  (0 = studio)
          - area_min: float
          - area_max: float
        
        Returns list of dicts with keys:
          title, price, currency, area, rooms, address, url, image, source
        """
        raise NotImplementedError

    def _listing(
        self,
        title="",
        price=None,
        currency="RUB",
        area=None,
        rooms=None,
        address="",
        url="",
        image="",
    ) -> Dict:
        """Helper to create a normalized listing dict."""
        return {
            "title": title,
            "price": price,
            "currency": currency,
            "area": area,
            "rooms": rooms,
            "address": address,
            "url": url if url.startswith("http") else self.base_url + url,
            "image": image,
            "source": self.display_name,
            "source_key": self.name,
        }
