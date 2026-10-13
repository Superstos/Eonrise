from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class QuestionLog:
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
            # What the run actually established, not just what it read. A claim is a
            # grounded down-relation term with the papers that support it and the sentence
            # it was read from. Nothing ranks on these yet -- the replay test that would
            # justify that cannot discriminate until runs are stored whole -- but a claim
            # not written down when it is made cannot be measured later at all.
            "claims": [
                {"text": t.get("text"), "relation": t.get("relation"),
                 "confidence": t.get("confidence"), "paper_ids": (t.get("paper_ids") or [])[:8],
                 "example": (t.get("examples") or [""])[0]}
                for t in record.get("terms", [])
                if t.get("relation") in {"mechanism", "measurement", "failure_mode", "method"}
                and t.get("confidence") in {"high", "medium"}
            ][:30],
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(slim, ensure_ascii=False) + "\n")

    def background_labels(self, root_topic: str = "", min_roots: int = 3) -> set[str]:
        """Labels that ranked highly on unrelated past questions.

        `computer science` and `artificial intelligence` led the top ten of every run
        regardless of the question. A label that keeps winning across different roots is
        describing the library, not the question.
        """
        if not self.path.exists():
            return set()
        seen: dict[str, set[str]] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            root = str(rec.get("root_topic", ""))
            if not root or root == root_topic:
                continue
            for concept in rec.get("concepts", [])[:12]:
                label = str(concept.get("label", "")).strip().lower()
                if label:
                    seen.setdefault(label, set()).add(root)
        return {label for label, roots in seen.items() if len(roots) >= min_roots}

    def recall(self, question: str, limit: int = 3) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        qt = _words(question)
        scored: list[tuple[int, dict[str, Any]]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = " ".join([str(rec.get("question", "")), str(rec.get("root_topic", "")),
                             *[str(c.get("label", "")) for c in rec.get("concepts", [])]])
            overlap = len(qt & _words(text))
            if overlap:
                scored.append((overlap, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]
