from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class MemoryStore:
    """Append-only JSONL memory so runs compound instead of restarting."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append_run(self, record: dict[str, Any]) -> None:
        slim = {
            "question": record.get("question", ""),
            "root_topic": record.get("root_topic", ""),
            "status": record.get("status", ""),
            "policy": record.get("policy", {}),
            "concepts": [
                {k: c.get(k) for k in ("label", "direction", "depth", "weight", "support")}
                for c in record.get("concepts", [])[:40]
            ],
            "papers": [
                {k: p.get(k) for k in ("paper_id", "title", "doi", "url", "year")}
                for p in record.get("papers", [])[:20]
            ],
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(slim, ensure_ascii=False) + "\n")

    def recall(self, question: str, limit: int = 3) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        qt = _tokens(question)
        scored: list[tuple[int, dict[str, Any]]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = " ".join([str(rec.get("question", "")), str(rec.get("root_topic", "")),
                             *[str(c.get("label", "")) for c in rec.get("concepts", [])]])
            overlap = len(qt & _tokens(text))
            if overlap:
                scored.append((overlap, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]
