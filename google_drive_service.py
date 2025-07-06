# START OF FILE google_drive_service.py #

import os
import io
import logging
import time
import asyncio
from functools import wraps

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# Импортируем конфигурационные данные из центрального файла
from config import (
    GOOGLE_DRIVE_CREDENTIALS_PATH,
    GOOGLE_DRIVE_TOKEN_PATH,
    GOOGLE_API_SCOPES
)

# Настраиваем логгер для этого модуля
logger = logging.getLogger(__name__)


# --- Декоратор для повторных попыток с экспоненциальной задержкой ---
def retry_on_http_error(max_retries=3, initial_delay=1, backoff_factor=2):
    """
    Декоратор для повторных попыток вызовов Google API при HttpError.
    Использует экспоненциальную задержку.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            for i in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except HttpError as e:
                    if e.resp.status in [403, 429, 500, 503]:
                        logger.warning(
                            f"Google API HttpError (Status: {e.resp.status}) при вызове {func.__name__}. "
                            f"Попытка {i + 1}/{max_retries}. Задержка {delay}с. Ошибка: {e}"
                        )
                        await asyncio.sleep(delay)
                        delay *= backoff_factor
                    else:
                        raise
            logger.error(f"Google API HttpError: Все {max_retries} попыток для {func.__name__} провалились.")
            raise

        return wrapper

    return decorator


class GoogleDriveService:
    """
    Класс для инкапсуляции всей логики взаимодействия с Google Drive API.
    """

    def __init__(self):
        """
        Инициализирует сервис. Пытается загрузить существующие учетные данные.
        """
        self.creds = None
        self.service = None
        self.creds_path_from_config = GOOGLE_DRIVE_CREDENTIALS_PATH
        self._load_credentials()

    def _load_credentials(self):
        """
        Загружает учетные данные из файла token.json.
        Если они действительны, инициализирует сервис API.
        Этот метод вызывается синхронно.
        """
        if os.path.exists(GOOGLE_DRIVE_TOKEN_PATH):
            try:
                self.creds = Credentials.from_authorized_user_file(GOOGLE_DRIVE_TOKEN_PATH, GOOGLE_API_SCOPES)
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    logger.info("Обновление просроченного токена Google Drive...")
                    self.creds.refresh(Request())
                    with open(GOOGLE_DRIVE_TOKEN_PATH, 'w') as token:
                        token.write(self.creds.to_json())

                self.service = build('drive', 'v3', credentials=self.creds)
                logger.info("Сервис Google Drive успешно инициализирован с существующими учетными данными.")
                return
            except Exception as e:
                logger.error(f"Ошибка при загрузке или обновлении токена '{GOOGLE_DRIVE_TOKEN_PATH}': {e}",
                             exc_info=True)
                self.creds = None
                self.service = None

        if os.path.exists(self.creds_path_from_config):
            logger.info(
                f"token.json не найден или недействителен. client_secret.json по пути '{self.creds_path_from_config}' присутствует. Ожидается авторизация.")
            self.creds = None
            self.service = None
        else:
            logger.info("Файлы токена и client_secret.json не найдены. Google Drive сервис не будет инициализирован.")
            self.creds = None
            self.service = None

    @property
    def is_authenticated(self) -> bool:
        """Свойство для проверки, аутентифицирован ли сервис."""
        return self.service is not None

    def get_auth_url(self) -> str | None:
        """
        Генерирует URL для аутентификации пользователя через OAuth.
        Возвращает URL или None в случае ошибки (например, отсутствует client_secret.json).
        """
        if not os.path.exists(self.creds_path_from_config):
            logger.error(f"Файл учетных данных '{self.creds_path_from_config}' не найден.")
            return None

        try:
            flow = InstalledAppFlow.from_client_secrets_file(self.creds_path_from_config, GOOGLE_API_SCOPES)
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            auth_url, _ = flow.authorization_url(prompt='consent')
            logger.info("URL для аутентификации успешно сгенерирован.")
            return auth_url
        except Exception as e:
            logger.error(f"Не удалось создать поток аутентификации: {e}")
            return None

    def complete_authentication(self, auth_code: str) -> bool:
        """
        Завершает процесс аутентификации, обменивая код на токен доступа.
        :param auth_code: Код авторизации, полученный пользователем от Google.
        :return: True в случае успеха, False в случае ошибки.
        """
        if not os.path.exists(self.creds_path_from_config):
            logger.error(f"Невозможно завершить аутентификацию: файл '{self.creds_path_from_config}' не найден.")
            return False

        try:
            flow = InstalledAppFlow.from_client_secrets_file(self.creds_path_from_config, GOOGLE_API_SCOPES)
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            flow.fetch_token(code=auth_code)

            self.creds = flow.credentials

            with open(GOOGLE_DRIVE_TOKEN_PATH, 'w') as token:
                token.write(self.creds.to_json())

            self.service = build('drive', 'v3', credentials=self.creds)
            logger.info("Аутентификация Google Drive успешно завершена.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при обмене кода авторизации на токен: {e}")
            self.creds = None
            self.service = None
            return False

    @retry_on_http_error()
    async def list_files(self, page_size: int = 10, q: str = None) -> list | None: # ИЗМЕНЕНО: Добавлен параметр q
        """
        Получает список файлов из Google Drive пользователя.
        :param page_size: Количество файлов для отображения.
        :param q: Строка запроса для фильтрации (например, "mimeType='application/pdf'").
        :return: Список файлов или None в случае ошибки.
        """
        if not self.is_authenticated:
            logger.warning("Попытка получить список файлов без аутентификации.")
            return None

        return await asyncio.to_thread(
            lambda: self.service.files().list(
                pageSize=page_size,
                q=q,  # ИЗМЕНЕНО: Передаем параметр q в API
                fields="nextPageToken, files(id, name, mimeType, size)"
            ).execute().get('files', [])
        )

    @retry_on_http_error()
    async def download_file(self, file_id: str, download_path: str) -> str | None:
        """
        Загружает файл с Google Drive по его ID.
        :param file_id: ID файла в Google Drive.
        :param download_path: Путь для сохранения файла (включая имя файла).
        :return: Путь к загруженному файлу в случае успеха, иначе None.
        """
        if not self.is_authenticated:
            logger.warning(f"Попытка скачать файл {file_id} без аутентификации.")
            return None

        os.makedirs(os.path.dirname(download_path), exist_ok=True)

        try:
            request = self.service.files().get_media(fileId=file_id)

            def _download():
                fh = io.FileIO(download_path, 'wb')
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                return download_path

            downloaded_path = await asyncio.to_thread(_download)
            logger.info(f"Файл с ID '{file_id}' успешно загружен в '{downloaded_path}'.")
            return downloaded_path
        except HttpError as error:
            logger.error(f"Произошла ошибка HTTP при загрузке файла {file_id}: {error}")
            raise
        except Exception as e:
            logger.error(f"Произошла непредвиденная ошибка при загрузке файла {file_id}: {e}")
            return None

    @retry_on_http_error()
    async def upload_file(self, file_path: str, file_name: str, mime_type: str) -> str | None:
        """
        Загружает файл на Google Drive.
        :param file_path: Локальный путь к файлу для загрузки.
        :param file_name: Имя файла, под которым он будет сохранен на Google Drive.
        :param mime_type: MIME-тип файла (например, 'application/pdf', 'text/plain').
        :return: ID загруженного файла в Google Drive или None в случае ошибки.
        """
        if not self.is_authenticated:
            logger.warning(f"Попытка загрузить файл {file_name} без аутентификации.")
            return None

        if not os.path.exists(file_path):
            logger.error(f"Локальный файл для загрузки не найден: {file_path}")
            return None

        try:
            # Создаем метаданные файла
            file_metadata = {'name': file_name}
            media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)

            # Выполняем загрузку в отдельном потоке, так как это блокирующая операция
            def _upload():
                uploaded_file = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()
                return uploaded_file.get('id')

            file_id = await asyncio.to_thread(_upload)
            logger.info(f"Файл '{file_name}' успешно загружен на Google Drive. ID: {file_id}")
            return file_id
        except HttpError as error:
            logger.error(f"Произошла ошибка HTTP при загрузке файла на Google Drive: {error}", exc_info=True)
            raise  # Перебрасываем, чтобы декоратор мог перехватить
        except Exception as e:
            logger.error(f"Произошла непредвиденная ошибка при загрузке файла на Google Drive: {e}", exc_info=True)
            return None


# Этот блок полезен для первоначальной ручной настройки и отладки.
if __name__ == '__main__':
    import asyncio

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    print("Запущен скрипт для ручной аутентификации Google Drive...")

    if not os.path.exists(GOOGLE_DRIVE_CREDENTIALS_PATH):
        print(f"Критическая ошибка: Файл '{GOOGLE_DRIVE_CREDENTIALS_PATH}' не найден.")
        print("Пожалуйста, скачайте его из Google Cloud Console и поместите в корень проекта.")
    else:
        drive_service = GoogleDriveService()


        async def run_manual_auth():
            if not drive_service.is_authenticated:
                print("\nСервис не аутентифицирован. Начинаем процесс аутентификации.")
                auth_url = drive_service.get_auth_url()
                if auth_url:
                    print("\n1. Перейдите по следующей ссылке в браузере:")
                    print(f"   {auth_url}")
                    print("\n2. Авторизуйтесь и скопируйте код, который предоставит Google.")
                    auth_code = input("3. Вставьте полученный код сюда и нажмите Enter: ")

                    if drive_service.complete_authentication(auth_code.strip()):
                        print("\n[УСПЕХ] Аутентификация прошла успешно. Файл 'token.json' создан/обновлен.")
                    else:
                        print("\n[ОШИБКА] Не удалось завершить аутентификацию. Проверьте код и попробуйте снова.")
                else:
                    print("\n[ОШИБКА] Не удалось получить URL для аутентификации.")

            if drive_service.is_authenticated:
                print("\n[ПРОВЕРКА] Сервис аутентифицирован. Запрашиваем список файлов...")
                files = await drive_service.list_files()
                if files is not None:
                    if not files:
                        print("Файлы в вашем Google Drive не найдены.")
                    else:
                        print("\nСписок файлов (до 10):")
                        for file in files:
                            print(f" - {file['name']} (ID: {file['id']})")
                else:
                    print("Не удалось получить список файлов.")

                # Пример загрузки тестового файла
                test_file_path = "test_upload.txt"
                with open(test_file_path, "w") as f:
                    f.write("This is a test file to upload to Google Drive.")
                print(f"\nПопытка загрузки тестового файла '{test_file_path}'...")
                uploaded_id = await drive_service.upload_file(test_file_path, "TestUploadFromBot.txt", "text/plain")
                if uploaded_id:
                    print(f"Тестовый файл загружен. ID: {uploaded_id}")
                else:
                    print("Не удалось загрузить тестовый файл.")
                os.remove(test_file_path)


        asyncio.run(run_manual_auth())

# END OF FILE google_drive_service.py #