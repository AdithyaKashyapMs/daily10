"""
Text processing: chunking (recursive splitter with overlap) and BM25 keyword search,
used to split notes into topics and to match past-paper questions to topics.
"""

import math
import re
from collections import Counter, defaultdict

from langchain_text_splitters import RecursiveCharacterTextSplitter

from daily10 import config

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP, separators=["\n\n", "\n", ". ", " ", ""]
)


def chunk_text(text: str) -> list[str]:
    return [c.strip() for c in _splitter.split_text(text) if c.strip()]


K1, B = 1.5, 0.75
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]")
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i if in into is it its my of on or so that the their "
    "them then there these this to was what when where which who why will with you your".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_SUFFIXES = ("ations", "ation", "ings", "ing", "ers", "er", "ies", "es", "ed", "ly", "s")


def _stem(word: str) -> str:
    """Crude suffix stripping, so autoscaling / autoscaler / autoscale share a term."""
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[: -len(suf)] + ("y" if suf == "ies" else "")
    return word.rstrip("e") if len(word) > 5 else word


def search_tokenize(text: str) -> list[str]:
    """Tokens for passage search: words, CamelCase / snake_case parts (HorizontalPodAutoscaler ->
    horizontal, pod, autoscaler) and their stems, so a query needn't use the exact identifier."""
    out = []
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.\-]*[A-Za-z0-9]|[A-Za-z0-9]", text):
        whole = raw.lower()
        if whole in STOPWORDS:
            continue
        parts = {p.lower() for piece in re.split(r"[_.\-]", raw) for p in _CAMEL_RE.findall(piece)}
        out.append(whole)
        out.extend(_stem(p) for p in parts if p not in STOPWORDS and (p != whole or _stem(p) != p))
    return out


class BM25Index:
    """Okapi BM25 over a list of {"content": ...} docs: rare terms count more, long docs don't win by length."""

    def __init__(self, docs: list[dict], tokenizer=tokenize):
        self.docs = docs
        self.tokenize = tokenizer
        self.tf = [Counter(tokenizer(d["content"])) for d in docs]
        self.lengths = [sum(t.values()) for t in self.tf]
        self.avgdl = (sum(self.lengths) / len(docs)) if docs else 0.0
        self.postings: dict[str, list[int]] = defaultdict(list)
        for i, tf in enumerate(self.tf):
            for term in tf:
                self.postings[term].append(i)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - len(ids) + 0.5) / (len(ids) + 0.5)) for t, ids in self.postings.items()}

    def search(self, query: str, limit: int = 15) -> list[dict]:
        scores: dict[int, float] = defaultdict(float)
        for term in set(self.tokenize(query)):
            if term not in self.idf:
                continue
            for i in self.postings[term]:
                tf = self.tf[i][term]
                scores[i] += self.idf[term] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * self.lengths[i] / self.avgdl))
        best = sorted(scores, key=lambda i: -scores[i])[:limit]
        return [{**self.docs[i], "score": scores[i]} for i in best]
