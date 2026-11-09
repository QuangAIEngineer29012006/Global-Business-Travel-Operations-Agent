import hashlib

import numpy as np

from .text import normalize

# Function words that carry no retrieval signal once accents are stripped. "bao" is kept on purpose:
# it starts "bảo hành", and bigrams still need it.
STOPWORDS = {"la", "cua", "va", "cho", "toi", "minh", "ban", "co", "khong", "duoc", "nhung", "cac", "mot",
             "nay", "do", "thi", "se", "da", "dang", "voi", "trong", "tren", "khi", "neu", "de", "hay",
             "hoac", "ve", "theo", "tu", "den", "gi", "nao", "the", "nhu", "vay", "a", "oi", "em", "anh",
             "chi", "shop", "ma", "rat", "nhe", "can", "muon", "biet", "hoi"}


def features(text):
    tokens = normalize(text).split()
    feats = [(t, 1.0) for t in tokens if t not in STOPWORDS]
    feats += [(f"{a}_{b}", 1.5) for a, b in zip(tokens, tokens[1:])]
    feats += [(f"#{t[i:i + 3]}", 0.3) for t in tokens if len(t) > 3 for i in range(len(t) - 2)]
    return feats


class FakeEmbedder:
    """Deterministic hashed bag-of-ngrams over accent-free text; lexical, offline, reproducible."""
    provider = "fake"
    model = "hashed-ngram-v1"
    revision = "1"
    dimension = 512
    query_encoding = document_encoding = "normalize(lower, no accents) -> unigram + bigram + char-trigram, signed hashing"
    # Cosine cut-off for context; scores are only comparable within one embedding model.
    min_score = 0.12

    def _embed(self, text):
        vector = np.zeros(self.dimension, dtype=np.float32)
        for feature, weight in features(text):
            digest = int.from_bytes(hashlib.md5(feature.encode()).digest()[:8], "big")
            vector[digest % self.dimension] += weight if digest >> 63 else -weight
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def embed_documents(self, chunks):
        return np.stack([self._embed(c.text) for c in chunks]) if chunks else np.zeros((0, self.dimension), np.float32)

    def embed_query(self, text):
        return self._embed(text)
