from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import numpy as np

MIN_TOKENS = 25
MIN_DISTINCT_TOKENS = 8
OTHER = "other"

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

_NGRAM_MIN = 3
_NGRAM_MAX = 5
_PRIME = np.uint64(1000003)
_MASK64 = (1 << 64) - 1
_SALTS = {n: np.uint64((n * 0x9E3779B97F4A7C15) & _MASK64)
          for n in range(_NGRAM_MIN, _NGRAM_MAX + 1)}
_MIX1 = np.uint64(0xFF51AFD7ED558CCD)
_MIX2 = np.uint64(0xC4CEB9FE1A85EC53)
_SHIFT = np.uint64(33)


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def tokenize(normalized: str) -> list[str]:
    return _WORD.findall(normalized)


def _avalanche(values: np.ndarray) -> np.ndarray:
    values = values ^ (values >> _SHIFT)
    values = values * _MIX1
    values = values ^ (values >> _SHIFT)
    values = values * _MIX2
    return values ^ (values >> _SHIFT)


def _ngram_unit(normalized: str, n_features: int) -> np.ndarray:
    out = np.zeros(n_features, dtype=np.float32)
    codes = np.frombuffer(normalized.encode("utf-32-le"), dtype=np.uint32).astype(np.uint64)
    mask = np.uint64(n_features - 1)
    parts = []
    for n in range(_NGRAM_MIN, _NGRAM_MAX + 1):
        count = codes.size - n + 1
        if count <= 0:
            continue
        rolling = np.zeros(count, dtype=np.uint64)
        for offset in range(n):
            rolling = rolling * _PRIME + codes[offset:offset + count]
        parts.append(_avalanche(rolling + _SALTS[n]) & mask)
    if not parts:
        return out
    indices, counts = np.unique(np.concatenate(parts), return_counts=True)
    values = counts.astype(np.float32)
    norm = float(np.sqrt(np.dot(values, values)))
    if norm > 0:
        values /= norm
    out[indices.astype(np.int64)] = values
    return out


class LanguageDetector:
    def __init__(self, model_path: str | Path) -> None:
        self.path = Path(model_path)
        with np.load(self.path, allow_pickle=False) as archive:
            self.classes = [str(name) for name in archive["classes"]]
            self.n_features = int(archive["n_features"])
            self.threshold = float(archive["threshold"])
            self._weights = archive["weights"].astype(np.float32) * archive["scales"]
            self._bias = archive["bias"].astype(np.float32)
            lexicon = json.loads(str(archive["lexicon"]))
        if lexicon["languages"] != self.classes:
            raise ValueError(f"{self.path.name}: lexicon languages do not match model classes")
        expected = self.n_features + 2 * len(self.classes)
        if self._weights.shape != (expected, len(self.classes)):
            raise ValueError(f"{self.path.name}: expected {expected} feature rows, "
                             f"got {self._weights.shape[0]}")
        self._words = [frozenset(lexicon["words"][name]) for name in self.classes]
        self._marks = [frozenset(lexicon["marks"][name]) for name in self.classes]

    def _lexicon_unit(self, tokens: list[str]) -> np.ndarray:
        out = np.zeros(2 * len(self.classes), dtype=np.float32)
        if not tokens:
            return out
        joined = "".join(tokens)
        for index in range(len(self.classes)):
            out[index] = sum(1 for token in tokens if token in self._words[index]) / len(tokens)
            if joined:
                out[len(self.classes) + index] = sum(
                    1 for char in joined if char in self._marks[index]) / len(joined)
        norm = float(np.linalg.norm(out))
        return out / norm if norm > 0 else out

    def _probabilities(self, normalized: str, tokens: list[str]) -> np.ndarray:
        vector = np.concatenate([_ngram_unit(normalized, self.n_features),
                                 self._lexicon_unit(tokens)])
        scored = vector @ self._weights + self._bias
        shifted = np.exp(scored - scored.max())
        return (shifted / shifted.sum()).astype(np.float32)

    def detect(self, text: str) -> str | None:
        normalized = normalize(text or "")
        tokens = tokenize(normalized)
        if len(tokens) < MIN_TOKENS or len(set(tokens)) < MIN_DISTINCT_TOKENS:
            return None
        probabilities = self._probabilities(normalized, tokens)
        top = int(np.argmax(probabilities))
        if self.classes[top] == OTHER or float(probabilities[top]) < self.threshold:
            return None
        return self.classes[top]
