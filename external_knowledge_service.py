# START OF FILE external_knowledge_service.py #

import logging

from config import GOOGLE_CSE_ID, GOOGLE_API_KEY_SEARCH

# ИЗМЕНЕНО: Инициализация логгера перенесена в начало файла
logger = logging.getLogger(__name__)

# LangChain предоставляет удобные обертки для различных API
try:
    from langchain_community.utilities import WikipediaAPIWrapper
    from langchain_google_community import GoogleSearchAPIWrapper
except ImportError:
    # Логируем предупреждение, если библиотеки не установлены.
    # Флаги останутся None, и функционал будет отключен.
    WikipediaAPIWrapper = None
    GoogleSearchAPIWrapper = None
    # Теперь этот вызов логгера будет работать корректно
    logger.warning("Не установлены все необходимые библиотеки для внешнего поиска (langchain-community, langchain-google-community). Функционал поиска будет ограничен.")


class ExternalKnowledgeService:
    """
    Сервис для поиска информации во внешних источниках, таких как Wikipedia и Google Search.
    """

    def __init__(self):
        """
        Инициализирует доступные инструменты поиска.
        """
        self.wikipedia = self._setup_wikipedia()
        self.google_search = self._setup_google_search()

        if not self.wikipedia and not self.google_search:
            logger.warning("Ни один из внешних сервисов поиска не инициализирован. Функционал будет недоступен.")
        elif self.wikipedia or self.google_search:
            # Собираем список доступных источников для логирования
            available_sources = []
            if self.wikipedia:
                available_sources.append("Wikipedia")
            if self.google_search:
                available_sources.append("Google Search")
            logger.info("Сервис внешнего поиска инициализирован. Доступны следующие источники: %s",
                        ", ".join(available_sources))


    def _setup_wikipedia(self) -> WikipediaAPIWrapper | None:
        """Настраивает и возвращает клиент для Wikipedia."""
        if not WikipediaAPIWrapper:
            # Предупреждение об импорте уже было выше, здесь просто возвращаем None
            return None

        try:
            # Устанавливаем русский язык и загружаем только топ-1 результат
            wiki_client = WikipediaAPIWrapper(lang="ru", top_k_results=1, doc_content_chars_max=4000)
            logger.info("Клиент Wikipedia успешно инициализирован.")
            return wiki_client
        except Exception as e:
            logger.error(f"Не удалось инициализировать WikipediaAPIWrapper: {e}", exc_info=True)
            return None

    def _setup_google_search(self) -> GoogleSearchAPIWrapper | None:
        """Настраивает и возвращает клиент для Google Search."""
        if not GoogleSearchAPIWrapper:
            # Предупреждение об импорте уже было выше, здесь просто возвращаем None
            return None

        if not GOOGLE_API_KEY_SEARCH or not GOOGLE_CSE_ID:
            logger.warning(
                "Ключи для Google Search API (GOOGLE_API_KEY_SEARCH, GOOGLE_CSE_ID) не заданы в конфиге. Поиск в Google недоступен.")
            return None
        try:
            search_client = GoogleSearchAPIWrapper(
                google_api_key=GOOGLE_API_KEY_SEARCH,
                google_cse_id=GOOGLE_CSE_ID
            )
            logger.info("Клиент Google Search успешно инициализирован.")
            return search_client
        except Exception as e:
            logger.error(f"Не удалось инициализировать GoogleSearchAPIWrapper: {e}", exc_info=True)
            return None

    def search(self, query: str) -> tuple[str | None, str | None]:
        """
        Выполняет поиск по внешним источникам.
        Стратегия: сначала Wikipedia, потом Google.

        :param query: Поисковый запрос.
        :return: Кортеж (найденный_текст, имя_источника) или (None, None), если ничего не найдено.
        """
        # Попытка поиска в Wikipedia
        if self.wikipedia:
            try:
                logger.info(f"Поиск в Wikipedia по запросу: '{query}'")
                result_wiki = self.wikipedia.run(query)
                # Проверяем, что результат не пустой, содержит не только пробелы и не является стандартным сообщением об отсутствии результатов
                if result_wiki and result_wiki.strip() and "no good wikipedia" not in result_wiki.lower():
                    logger.info("Найдена релевантная информация в Wikipedia.")
                    return result_wiki, "Wikipedia"
                else:
                    logger.info("Wikipedia не нашла релевантной информации по запросу: '%s'.", query)
            except Exception as e:
                logger.error(f"Ошибка при поиске в Wikipedia для запроса '{query}': {e}", exc_info=True)

        # Если в Wikipedia ничего не найдено, ищем в Google
        if self.google_search:
            try:
                logger.info(f"Поиск в Google по запросу: '{query}'")
                result_google = self.google_search.run(query)
                # Проверяем, что результат не пустой, содержит не только пробелы и не является стандартным сообщением об отсутствии результатов
                if result_google and result_google.strip() and "no good results" not in result_google.lower():
                    logger.info("Найдена релевантная информация в Google Search.")
                    return result_google, "Google Search"
                else:
                    logger.info("Google Search не нашел релевантной информации по запросу: '%s'.", query)
            except Exception as e:
                logger.error(f"Ошибка при поиске в Google для запроса '{query}': {e}", exc_info=True)

        logger.info("Во внешних источниках ничего не найдено для запроса: '%s'", query)
        return None, None

# END OF FILE external_knowledge_service.py #