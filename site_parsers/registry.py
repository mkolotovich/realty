"""
Реестр парсеров.

Чтобы добавить новый сайт:
  1. Создайте файл в папке site_parsers/ (унаследуйтесь от BaseParser).
  2. Импортируйте класс ниже.
  3. Добавьте экземпляр в словарь PARSERS.
  4. Перезапустите сервер — источник появится в UI автоматически.
"""
from .vk_wall_parser import VkWallParser
from .incom_lnr_parser import IncomLnrParser

PARSERS: dict = {
    "vk_wall":   VkWallParser(),
    "incom_lnr": IncomLnrParser(),
}


def get_parser(name: str):
    return PARSERS.get(name)


def list_parsers():
    return [
        {"key": p.name, "name": p.display_name, "url": p.base_url}
        for p in PARSERS.values()
    ]
