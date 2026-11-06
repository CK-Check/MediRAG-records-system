import numpy as np
from langchain_core.embeddings import Embeddings


class DPHuggingFaceEmbeddings(Embeddings):
    """
    A custom wrapper that injects Differential Privacy (Laplacian noise)
    into document embeddings before they are stored in the local FAISS index.
    """
    
    def __init__(self, model_name="sentence-transformers/all-MiniLM-L6-v2",
                noise_scale=0.0, seed=None):
        self.model_name = model_name
        self.noise_scale = noise_scale
        self._model = None
        self._rng = np.random.default_rng(seed)  # type: ignore
        
    def _encode(self, texts):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # loaded lazily
            self._model = SentenceTransformer(self.model_name)
        return np.asarray(self._model.encode(texts, normalize_embeddings=True), dtype="float32")

    def embed_documents(self, texts):
        vecs = self._encode(texts)
        if self.noise_scale > 0:
            noise = self._rng.laplace(0.0, self.noise_scale, vecs.shape).astype("float32")
            vecs = vecs + noise
        return vecs.tolist()
    
    def embed_query(self, text):
        return self._encode([text])[0].tolist()