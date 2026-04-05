import os
import chromadb
from chromadb.utils import embedding_functions
from datetime import datetime


class SentiaMemory:
    def __init__(self, base_dir):
        print("[System] 正在初始化高维向量海马体 (ChromaDB + BGE-Small-ZH)...")

        self.db_path = os.path.join(base_dir, "models", "memory_db")
        if not os.path.exists(self.db_path):
            os.makedirs(self.db_path)

        self.client = chromadb.PersistentClient(path=self.db_path)

        try:
            self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="BAAI/bge-small-zh-v1.5"
            )

            # 4. 打开或创建专属的“长期日记本”集合
            self.collection = self.client.get_or_create_collection(
                name="sentia_long_term_memory",
                embedding_function=self.embedding_fn
            )

            count = self.collection.count()
            print(f"[System] 记忆激活成功！当前已存储 {count} 条长期记忆节点。")
            self.is_ready = True

        except Exception as e:
            print(f"[Error] 记忆植入失败！请检查网络或依赖库。\n错误详情: {e}")
            self.is_ready = False

    def _get_timestamp(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    def write_memory(self, event_description, emotion_tag="Neutral", importance=1):
        if not self.is_ready: return

        memory_id = f"mem_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        timestamp = self._get_timestamp()

        memory_text = f"[{timestamp}] [情绪:{emotion_tag}] {event_description}"

        try:
            self.collection.add(
                documents=[memory_text],
                metadatas=[{"timestamp": timestamp, "emotion": emotion_tag, "importance": importance}],
                ids=[memory_id]
            )
            # 核心事件才会打印到控制台，保持日志清爽
            if importance >= 4:
                print(f"[Memory] 核心事件已永久归档: {memory_text}")
        except Exception as e:
            print(f"[Warning] 记忆写入失败: {e}")

    def recall_memory(self, query_text, n_results=2):
        if not self.is_ready or self.collection.count() == 0:
            return ""

        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=min(n_results, self.collection.count())
            )

            documents = results.get('documents', [[]])[0]

            if not documents:
                return ""

            recalled_text = "[检索到的长期历史记忆]：\n" + "\n".join(documents)
            return recalled_text

        except Exception as e:
            print(f"[Warning] 记忆检索失败: {e}")
            return ""

    def get_last_shutdown_memory(self):
        if not self.is_ready or self.collection.count() == 0:
            return ""

        try:
            results = self.collection.get(
                where={"importance": 5},
                limit=1
            )

            if results and results.get('documents'):
                last_event = results['documents'][-1]
                return f"[极其重要的历史情绪残留]：在你上次运行程序时，发生了这件事 -> {last_event}。你在说第一句话时，必须极其强烈地带入这个情绪进行回复！"
            return ""

        except Exception:
            return ""