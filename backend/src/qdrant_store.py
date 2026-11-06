"""
qdrant_store.py  -  Vector store backed by Qdrant (an industry-standard vector database).

Two modes, SAME code:
  * Embedded (default): data lives in a folder, no server and no network port needed.
      Good for development, testing and a single machine.
  * Server: set the environment variable QDRANT_URL (e.g. http://127.0.0.1:6333).
      This is the production setup (a real Qdrant server, with replication, API keys, backups).

It keeps the same method names as SimpleVectorStore, so ingest.py and
agentic_pipeline.py need only an import change:
    from_documents / save_local / load_local / similarity_search

Note: in embedded mode only ONE process can open the folder at a time.
Run ingest.py first, close it, then start api.py.
"""
import os

from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.models import (Distance, FieldCondition, Filter, MatchValue,
                                  PayloadSchemaType, PointStruct, VectorParams)

COLLECTION = "patient_chunks"


def _open_client(folder):
    url = os.environ.get("QDRANT_URL")
    if url:
        return QdrantClient(url=url, api_key=os.environ.get("QDRANT_API_KEY"))
    return QdrantClient(path=str(folder))


class QdrantStore:
    def __init__(self, client, embeddings):
        self.client = client
        self.embeddings = embeddings

    @classmethod
    def from_documents(cls, docs, embeddings, folder):
        client = _open_client(folder)
        vectors = embeddings.embed_documents([d.page_content for d in docs])

        if client.collection_exists(COLLECTION):          # rebuild from scratch on every ingest
            client.delete_collection(COLLECTION)
        client.create_collection(COLLECTION, vectors_config=VectorParams(size=len(vectors[0]),
                                                                          distance=Distance.COSINE))
        if os.environ.get("QDRANT_URL"):   # on a real server, an index on patient_id keeps the filter fast
            client.create_payload_index(COLLECTION, field_name="patient_id",
                                        field_schema=PayloadSchemaType.KEYWORD)

        points = [PointStruct(id=i, vector=v, payload={"text": d.page_content, **d.metadata})
                  for i, (d, v) in enumerate(zip(docs, vectors))]
        for start in range(0, len(points), 256):            # upload in batches
            client.upsert(COLLECTION, points=points[start:start + 256])
        return cls(client, embeddings)

    def save_local(self, folder=None):
        """Nothing to do: Qdrant already saved the data when it was inserted."""

    @classmethod
    def load_local(cls, folder, embeddings, **_ignored):
        client = _open_client(folder)
        if not client.collection_exists(COLLECTION):
            raise FileNotFoundError(f"No Qdrant collection in {folder}. Run 'python ingest.py' first.")
        return cls(client, embeddings)

    def similarity_search(self, query, k=4, filter=None, **_ignored):
        """Top-k chunks; 'filter' like {"patient_id": "0aed8a17"} is applied INSIDE the database."""
        flt = None
        if filter:
            flt = Filter(must=[FieldCondition(key=key, match=MatchValue(value=val))
                               for key, val in filter.items()])
        result = self.client.query_points(COLLECTION, query=self.embeddings.embed_query(query),
                                          query_filter=flt, limit=k, with_payload=True)
        docs = []
        for point in result.points:
            payload = dict(point.payload)
            text = payload.pop("text")
            docs.append(Document(page_content=text, metadata=payload))
        return docs

    def close(self):
        self.client.close()
