# START OF FILE tests/test_knowledge_base_service.py #

import pytest
from unittest.mock import MagicMock, patch

# Патчим тяжелые зависимости на уровне модуля, чтобы они не загружались
# Это гарантирует, что при импорте KnowledgeBaseService его зависимости уже будут подменены
with patch('langchain_huggingface.HuggingFaceEmbeddings') as mock_embeddings:
    mock_embeddings.return_value = MagicMock()
    from knowledge_base_service import KnowledgeBaseService


@pytest.fixture
def clean_kb_service(mocker):
    """
    Фикстура, которая создает экземпляр KnowledgeBaseService в "чистом" состоянии,
    как будто программа только что запустилась и не нашла сохраненных файлов.
    service.vector_store здесь будет None.
    """
    mocker.patch('os.path.exists', return_value=False)
    mocker.patch('builtins.open', mocker.mock_open())

    service = KnowledgeBaseService()

    # Мокаем методы сохранения, чтобы они ничего не делали в тестах
    mocker.patch.object(service, '_save_source_map')
    mocker.patch.object(service, 'save_vector_store')

    return service


def test_add_text_to_empty_kb_calls_from_texts(clean_kb_service, mocker):
    """
    Проверяет, что при добавлении в пустую базу знаний (vector_store is None)
    вызывается FAISS.from_texts.
    """
    # 1. Подготовка
    test_text = "Это длинный текст для создания новой базы знаний." * 100
    test_metadata = {"source": "new_doc.txt", "source_id": "new_id_001"}

    # Создаем поддельный объект vector_store, который ВЕРНЕТСЯ после вызова from_texts
    mock_vector_store_instance = MagicMock()
    # Симулируем получение ID после создания базы
    mock_vector_store_instance.docstore._dict.keys.return_value = ["faiss_id_1", "faiss_id_2"]

    # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ ---
    # Патчим метод FAISS.from_texts в пространстве имен, где он используется
    # (в модуле knowledge_base_service), а не в langchain.
    mock_faiss_from_texts = mocker.patch(
        'knowledge_base_service.FAISS.from_texts',  # <-- Правильный путь для патча
        return_value=mock_vector_store_instance
    )

    # 2. Действие
    # clean_kb_service.vector_store изначально None
    clean_kb_service.add_text(test_text, test_metadata)

    # 3. Проверка
    # Теперь этот assert должен сработать, потому что мы правильно перехватили вызов
    mock_faiss_from_texts.assert_called_once()

    # Проверяем, что карта источников обновилась
    assert "new_id_001" in clean_kb_service.source_id_to_faiss_ids_map
    assert clean_kb_service.source_id_to_faiss_ids_map["new_id_001"] == ["faiss_id_1", "faiss_id_2"]

    # Проверяем, что было вызвано сохранение
    clean_kb_service.save_vector_store.assert_called_once()


def test_add_text_to_existing_kb_calls_add_texts(clean_kb_service, mocker):
    """
    Проверяет, что при добавлении в существующую базу знаний
    вызывается метод vector_store.add_texts.
    """
    # 1. Подготовка
    test_text = "Это текст для добавления в уже существующую базу." * 100
    test_metadata = {"source": "existing_doc.txt", "source_id": "existing_id_002"}

    # Симулируем существующую базу, назначив поддельный vector_store сервису
    mock_vector_store_instance = MagicMock()
    mock_vector_store_instance.add_texts.return_value = ["faiss_id_3", "faiss_id_4"]
    clean_kb_service.vector_store = mock_vector_store_instance

    # Патчим from_texts, чтобы убедиться, что он НЕ вызывается
    mock_faiss_from_texts = mocker.patch('knowledge_base_service.FAISS.from_texts')

    # 2. Действие
    clean_kb_service.add_text(test_text, test_metadata)

    # 3. Проверка
    # Проверяем, что был вызван метод .add_texts() у нашего мока
    clean_kb_service.vector_store.add_texts.assert_called_once()

    # Убеждаемся, что from_texts НЕ был вызван
    mock_faiss_from_texts.assert_not_called()

    # Проверяем карту источников
    assert "existing_id_002" in clean_kb_service.source_id_to_faiss_ids_map
    assert clean_kb_service.source_id_to_faiss_ids_map["existing_id_002"] == ["faiss_id_3", "faiss_id_4"]

# END OF FILE tests/test_knowledge_base_service.py #