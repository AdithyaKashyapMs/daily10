"""
Citation checks shared by every agent: an answer may only cite passages ("T12#3") and past exam
questions ("P7") that a tool actually returned. Anything else is reported as unverified.
"""

import re

CITATION = re.compile(r"\b(T\d+#\d+|P\d+)\b")
SOURCE_ID = re.compile(r"^(T\d+#\d+|P\d+)$")


def collect(node, seen: dict[str, dict], topic=None, topic_id=None) -> dict[str, dict]:
    """Add every passage / past question inside a tool result to `seen`, by citation id."""
    if isinstance(node, dict):
        topic = node.get("topic") if isinstance(node.get("topic"), str) else topic
        topic_id = node.get("topic_id", topic_id) if isinstance(node.get("topic_id"), int) else topic_id
        if node.get("id") is not None and "#" not in str(node.get("id")) and "passages" in node:
            topic_id = node["id"] if isinstance(node["id"], int) else topic_id   # a whole topic
            topic = node.get("title", topic)
        nid = str(node.get("id", ""))
        text = node.get("content") or node.get("text")
        if SOURCE_ID.match(nid) and isinstance(text, str):
            seen.setdefault(nid, {"id": nid, "topic": topic, "topic_id": topic_id, "text": text,
                                  **({"year": node.get("year")} if nid.startswith("P") else {})})
        for v in node.values():
            collect(v, seen, topic, topic_id)
    elif isinstance(node, list):
        for v in node:
            collect(v, seen, topic, topic_id)
    return seen


def check(cited, seen: dict[str, dict]) -> tuple[list[str], list[str]]:
    """(verified, unverified) citation ids, de-duplicated, in order."""
    valid, invalid = [], []
    for c in dict.fromkeys(str(c).strip().strip("[]") for c in cited or []):
        (valid if c in seen else invalid).append(c)
    return valid, invalid


def in_text(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(1) for m in CITATION.finditer(text)))
