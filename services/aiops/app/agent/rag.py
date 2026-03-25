import os
import json
import chromadb
from openai import OpenAI
from typing import Optional


class RAGManager:
    def __init__(self, chroma_url: str, collection_name: str, knowledge_dir: str, openai_api_key: str):
        self.knowledge_dir = knowledge_dir
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.chroma_client = chromadb.HttpClient(host=chroma_url.replace("http://", "").split(":")[0],
                                                  port=int(chroma_url.split(":")[-1]))
        self.collection = self.chroma_client.get_or_create_collection(name=collection_name)

    def _read_knowledge_files(self) -> list[dict]:
        """Scan knowledge dir for .md and .json files, return list of {content, source, type}."""
        docs = []
        for subdir in ["runbooks", "past_incidents"]:
            dir_path = os.path.join(self.knowledge_dir, subdir)
            if not os.path.exists(dir_path):
                continue
            for fname in os.listdir(dir_path):
                fpath = os.path.join(dir_path, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                doc_type = "runbook" if subdir == "runbooks" else "past_incident"
                if fname.endswith(".json"):
                    content = json.dumps(json.loads(content), indent=2)
                docs.append({"content": content, "source": fname, "type": doc_type})
        return docs

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using OpenAI API."""
        response = self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=texts
        )
        return [item.embedding for item in response.data]

    def load_knowledge(self) -> None:
        """Load knowledge files into ChromaDB if not already loaded."""
        existing = self.collection.count()
        if existing > 0:
            return
        docs = self._read_knowledge_files()
        if not docs:
            return
        texts = [d["content"] for d in docs]
        embeddings = self._embed(texts)
        self.collection.add(
            documents=texts,
            embeddings=embeddings,
            metadatas=[{"source": d["source"], "type": d["type"]} for d in docs],
            ids=[f"doc_{i}" for i in range(len(docs))]
        )

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """Search knowledge base for relevant docs."""
        query_embedding = self._embed([query])[0]
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        output = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                output.append({
                    "content": doc,
                    "source": results["metadatas"][0][i]["source"] if results["metadatas"] else "unknown",
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                })
        return output
