# START OF FILE knowledge_base_service.py #

import os
import logging
import json
from typing import List, Dict, Any, Tuple
import shutil

from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter

from config import VECTOR_STORE_PATH, SOURCE_MAP_PATH, EMBEDDING_MODEL_NAME

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200, length_function=len)
        logger.info("Инициализация модели встраивания... Это может занять некоторое время.")
        self.embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
        logger.info("Модель встраивания успешно загружена.")
        self.vector_store = self._load_vector_store()
        self.source_id_to_faiss_ids_map: Dict[str, List[str]] = self._load_source_map()

    def _load_vector_store(self) -> FAISS | None:
        folder_path, index_name = os.path.dirname(VECTOR_STORE_PATH), os.path.basename(VECTOR_STORE_PATH)
        if os.path.exists(f"{VECTOR_STORE_PATH}.faiss"):
            try:
                logger.info(f"Загрузка существующей базы знаний из {VECTOR_STORE_PATH}")
                return FAISS.load_local(folder_path=folder_path, index_name=index_name, embeddings=self.embeddings,
                                        allow_dangerous_deserialization=True)
            except Exception as e:
                logger.error(f"Ошибка при загрузке базы знаний: {e}. Будет создана новая база.", exc_info=True)
                if os.path.exists(f"{VECTOR_STORE_PATH}.faiss"): os.remove(f"{VECTOR_STORE_PATH}.faiss")
                if os.path.exists(f"{VECTOR_STORE_PATH}.pkl"): os.remove(f"{VECTOR_STORE_PATH}.pkl")
                return None
        logger.info("Существующая база знаний не найдена. Будет создана новая при добавлении данных.")
        return None

    def _load_source_map(self) -> Dict[str, List[str]]:
        if os.path.exists(SOURCE_MAP_PATH):
            try:
                with open(SOURCE_MAP_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Ошибка при загрузке карты источников {SOURCE_MAP_PATH}: {e}", exc_info=True)
                if os.path.exists(SOURCE_MAP_PATH): os.remove(SOURCE_MAP_PATH)
        return {}

    def _save_source_map(self):
        os.makedirs(os.path.dirname(SOURCE_MAP_PATH), exist_ok=True)
        try:
            with open(SOURCE_MAP_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.source_id_to_faiss_ids_map, f, indent=4)
        except Exception as e:
            logger.error(f"Ошибка при сохранении карты источников в {SOURCE_MAP_PATH}: {e}", exc_info=True)

    def add_text(self, text: str, metadata: Dict[str, Any]):
        source_id = metadata.get('source_id')
        if source_id and source_id in self.source_id_to_faiss_ids_map:
            logger.info(f"Обнаружены существующие данные для source_id '{source_id}'. Удаляю старые чанки.")
            self.delete_by_source_id(source_id)

        chunks = self.text_splitter.split_text(text)
        if not chunks:
            logger.warning("Текст не содержит чанков для добавления в базу знаний.")
            return

        metadatas = [metadata] * len(chunks)
        try:
            if self.vector_store:
                faiss_doc_ids = self.vector_store.add_texts(texts=chunks, metadatas=metadatas)
            else:
                self.vector_store = FAISS.from_texts(texts=chunks, embedding=self.embeddings, metadatas=metadatas)
                faiss_doc_ids = list(self.vector_store.docstore._dict.keys())

            if source_id:
                self.source_id_to_faiss_ids_map[source_id] = faiss_doc_ids
            self.save_vector_store()
        except Exception as e:
            logger.error(f"Ошибка при добавлении текста в FAISS: {e}", exc_info=True)

    def delete_by_source_id(self, source_id: str) -> bool:
        if not self.vector_store or source_id not in self.source_id_to_faiss_ids_map:
            return False

        faiss_ids_to_delete = self.source_id_to_faiss_ids_map.pop(source_id)
        try:
            self.vector_store.delete(faiss_ids_to_delete)
            self.save_vector_store()
            logger.info(f"Успешно удалено {len(faiss_ids_to_delete)} чанков для source_id '{source_id}'.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении чанков для source_id '{source_id}': {e}", exc_info=True)
            self.source_id_to_faiss_ids_map[source_id] = faiss_ids_to_delete  # Rollback
            return False

    def save_vector_store(self):
        if self.vector_store:
            folder_path, index_name = os.path.dirname(VECTOR_STORE_PATH), os.path.basename(VECTOR_STORE_PATH)
            os.makedirs(folder_path, exist_ok=True)
            self.vector_store.save_local(folder_path=folder_path, index_name=index_name)
            self._save_source_map()

    def clear_all(self):
        self.vector_store = None
        self.source_id_to_faiss_ids_map = {}
        if os.path.exists(f"{VECTOR_STORE_PATH}.faiss"): os.remove(f"{VECTOR_STORE_PATH}.faiss")
        if os.path.exists(f"{VECTOR_STORE_PATH}.pkl"): os.remove(f"{VECTOR_STORE_PATH}.pkl")
        if os.path.exists(SOURCE_MAP_PATH): os.remove(SOURCE_MAP_PATH)
        logger.info("База знаний полностью очищена.")

    def search(self, query: str, k: int = 4) -> list:
        if not self.vector_store: return []
        try:
            return self.vector_store.similarity_search(query, k=k)
        except Exception as e:
            logger.error(f"Ошибка при поиске в базе знаний: {e}", exc_info=True)
            return []

    def get_indexed_sources(self) -> List[Dict[str, str]]:
        """Возвращает список уникальных источников, которые есть в базе знаний."""
        if not self.vector_store:
            return []

        sources = {}
        for doc_id in self.vector_store.docstore._dict:
            metadata = self.vector_store.docstore._dict[doc_id].metadata
            source_id = metadata.get('source_id')
            if source_id and source_id not in sources:
                sources[source_id] = {
                    'source_id': source_id,
                    'source': metadata.get('source', 'Неизвестное имя файла')
                }

        return list(sources.values())

# END OF FILE knowledge_base_service.py #