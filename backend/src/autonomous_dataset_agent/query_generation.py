from __future__ import annotations

import re


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_phrase(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s-]+", " ", value.lower())
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _build_context_phrase(prompt: str, class_name: str) -> str:
    prompt_normalized = _normalize_phrase(prompt)
    class_normalized = _normalize_phrase(class_name)
    if not prompt_normalized:
        return ""
    if class_normalized:
        prompt_normalized = prompt_normalized.replace(class_normalized, " ")
    prompt_normalized = _WHITESPACE_RE.sub(" ", prompt_normalized).strip()
    return prompt_normalized


def generate_queries_for_class(prompt: str, class_name: str) -> list[str]:
    class_normalized = _normalize_phrase(class_name)
    context = _build_context_phrase(prompt, class_name)

    queries = [
        _normalize_phrase(prompt),
        class_normalized,
        f"{class_normalized} {context}".strip(),
        f"{class_normalized} side view",
        f"{class_normalized} close up",
        f"{class_normalized} indoor {context}".strip(),
        f"{class_normalized} loading dock",
        f"worker using {class_normalized} {context}".strip(),
    ]

    ordered: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = _normalize_phrase(query)
        if not normalized or normalized in seen:
            continue
        ordered.append(normalized)
        seen.add(normalized)
    return ordered


def generate_class_queries(prompt: str, classes: list[str]) -> dict[str, list[str]]:
    return {class_name: generate_queries_for_class(prompt, class_name) for class_name in classes}
