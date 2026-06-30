"""
memory_store.py — Jarvis's long-term memory.

This is the "learns by itself" part. It's not magic: it's a simple,
durable notebook that:
  1. Saves things worth remembering (facts, preferences, past topics)
  2. Finds the most RELEVANT saved memories for whatever you just said
  3. Hands those back so the AI's prompt includes "what it knows about you"

This is the real-world version of RAG (Retrieval-Augmented Generation)
without needing a heavyweight embeddings model or vector database server.
For a personal assistant's memory size (hundreds–thousands of notes),
a simple keyword/TF-IDF style scorer works very well and has zero
extra dependencies or API cost.

If you later want smarter semantic search (catching meaning, not just
keyword overlap), swap `score()` below for a real embedding model —
the rest of the system doesn't need to change.
"""

import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path

MEMORY_FILE = Path(__file__).parent / "memory" / "memories.jsonl"
MEMORY_FILE.parent.mkdir(exist_ok=True)

STOPWORDS = set("""
a an the is are was were be been being to of in on at for with and or
but if then so this that these those i you he she it we they my your
his her its our their me him them us do does did have has had will
would can could should may might just not no yes about as by from
what who whom which where why how know knows knew tell tells told
user users
""".split())


def _stem(word: str) -> str:
    """Very small, crude stemmer: just enough to match plurals/verb forms
    like 'lives'/'live' or 'preferences'/'preference'. Not linguistically
    rigorous, but good enough for personal-memory recall."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"          # categories -> categor+y... close enough
    if word.endswith("es") and len(word) > 4 and word[-3] not in "aeiou":
        return word[:-1]                 # lives -> live, likes -> like (keep the e)
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]                 # cats -> cat, preferences -> preference
    return word


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return [_stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


class MemoryStore:
    def __init__(self, path: Path = MEMORY_FILE):
        self.path = path
        self.memories: list[dict] = []
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.memories.append(json.loads(line))

    def add(self, text: str, kind: str = "note", source: str = "conversation"):
        """Save a new memory. kind: 'fact' | 'preference' | 'note' | 'event'."""
        entry = {
            "text": text,
            "kind": kind,
            "source": source,
            "timestamp": time.time(),
        }
        self.memories.append(entry)
        with open(self.path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def all(self) -> list[dict]:
        return list(self.memories)

    def _score(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """Overlap score using prefix matching (catches near-misses like
        'preference' vs 'prefer' that exact-match stemming alone would miss),
        weighted by how rare/specific the matching term is in the document.
        Good enough to surface relevant memories without an embeddings model."""
        if not doc_tokens:
            return 0.0
        doc_counts = Counter(doc_tokens)
        score = 0.0
        for qt in query_tokens:
            for dt, count in doc_counts.items():
                if qt == dt:
                    score += 1.0 + math.log(1 + count)
                elif len(qt) >= 4 and len(dt) >= 4 and (qt.startswith(dt) or dt.startswith(qt)):
                    score += 0.6 + math.log(1 + count)  # partial credit for near-match
        # normalize a bit by document length so short precise notes aren't buried
        return score / math.sqrt(len(doc_tokens))

    def search(self, query: str, top_k: int = 5, min_score: float = 0.3) -> list[dict]:
        """Return the top_k most relevant memories to the query."""
        q_tokens = _tokenize(query)
        if not q_tokens or not self.memories:
            return []

        scored = []
        for m in self.memories:
            doc_tokens = _tokenize(m["text"])
            s = self._score(q_tokens, doc_tokens)
            if s >= min_score:
                scored.append((s, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]]

    def recent(self, n: int = 5) -> list[dict]:
        return self.memories[-n:]
