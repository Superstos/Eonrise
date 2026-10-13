from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _select_fields(record, fields):
    return {key: record.get(key) for key in fields}


def _claim(term):
    return {"text": term.get("text"), "relation": term.get("relation"),
            "confidence": term.get("confidence"), "paper_ids": (term.get("paper_ids") or [])[:8],
            "example": (term.get("examples") or [""])[0]}


def _grounded_claim(term):
    return (term.get("relation") in {"mechanism", "measurement", "failure_mode", "method"}
            and term.get("confidence") in {"high", "medium"})


def _run_record(record):
    return {
        "question": record.get("question", ""),
        "root_topic": record.get("root_topic", ""),
        "status": record.get("status", ""),
        "policy": record.get("policy", {}),
        "concepts": [_select_fields(c, ("label", "direction", "depth", "weight", "support"))
                     for c in record.get("concepts", [])[:40]],
        "papers": [_select_fields(p, ("paper_id", "title", "doi", "url", "year"))
                   for p in record.get("papers", [])[:20]],
        "claims": _claims(record),
    }


# What the run actually established, not just what it read. A claim is a
# grounded down-relation term with the papers that support it and the sentence
# it was read from. Nothing ranks on these yet -- the replay test that would
# justify that cannot discriminate until runs are stored whole -- but a claim
# not written down when it is made cannot be measured later at all.
def _claims(record):
    return [_claim(t) for t in record.get("terms", []) if _grounded_claim(t)][:30]


def _read_records(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _record_text(record):
    return " ".join([str(record.get("question", "")), str(record.get("root_topic", "")),
                     *[str(c.get("label", "")) for c in record.get("concepts", [])]])


def _remember_labels(seen, record):
    root = str(record.get("root_topic", ""))
    for concept in record.get("concepts", [])[:12]:
        label = str(concept.get("label", "")).strip().lower()
        if label:
            seen.setdefault(label, set()).add(root)


class QuestionLog:
    """Append-only JSONL memory so runs compound instead of restarting."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append_run(self, record: dict[str, Any]) -> None:
        slim = _run_record(record)
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
        for rec in _read_records(self.path):
            root = str(rec.get("root_topic", ""))
            if not root or root == root_topic:
                continue
            _remember_labels(seen, rec)
        return _frequent_labels(seen, min_roots)

    def recall(self, question: str, limit: int = 3) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        qt = _words(question)
        scored: list[tuple[int, dict[str, Any]]] = []
        for rec in _read_records(self.path):
            text = _record_text(rec)
            overlap = len(qt & _words(text))
            if overlap:
                scored.append((overlap, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]


def _frequent_labels(seen, min_roots):
    return {label for label, roots in seen.items() if len(roots) >= min_roots}
