"""Map textbook chapters to oral medicine focus questions (definitions and essays)."""

from __future__ import annotations

import re
from typing import Optional
from yureader.oral_focus import load_oral_focus, SUBJECT_SOURCES

# Maps book_id to oral focus subject_id
BOOK_TO_SUBJECT: dict[str, str] = {
    s["book_id"]: s["id"] for s in SUBJECT_SOURCES
}

# Specific manual aliases where wording differs slightly between book editions and question docx
CHAPTER_ALIASES: dict[tuple[str, str], str] = {
    ("dental-pulp-5e", "牙髓根尖周病治疗的生物学基础"): "牙髓及根尖周病治疗的生物学基础",
    ("dental-pulp-5e", "牙髓根尖周病的病因及发病机制"): "牙髓病和根尖周病的病因和发病机制",
    ("dental-pulp-5e", "牙髓根尖周病的治疗计划"): "牙髓病和根尖周病治疗计划",
    ("prosthodontics-8e", "牙列缺损的固定局部义齿修复"): "牙列缺损的固定义齿修复",
    ("prosthodontics-8e", "其他口腔修复治疗"): "颌面缺损／牙周病／咬合病／颞下颌关节病修复",
    ("oral-pathology-8e", "牙源性肿瘤和瘤样病变"): "牙源性肿瘤和瘤样变",
    ("oral-pathology-8e", "口腔颌面部其他组织来源的肿瘤和瘤样病变"): "口腔颌面部其他组织来源的肿瘤和瘤样变",
}

_MAPPING_CACHE: dict[tuple[str, str], list[dict]] = {}


def normalize_chapter_title(text: str) -> str:
    """Normalize chapter title by removing chapter prefixes, punctuation, and synonyms."""
    t = re.sub(r"^(第[一二三四五六七八九十百\d]+章|\d+)\s*[、.．\s]*", "", str(text or "")).strip()
    t = re.sub(r"[\s·•:：,，。.!！?？()（）\[\]【】/／与及和病变]", "", t)
    t = t.replace("过敏", "敏感").replace("变", "")
    return t


def get_chapter_questions(book_id: str, chapter_title: str) -> list[dict]:
    """Return all oral focus questions mapped to a book chapter."""
    if not book_id or not chapter_title:
        return []

    cache_key = (book_id, chapter_title.strip())
    if cache_key in _MAPPING_CACHE:
        return _MAPPING_CACHE[cache_key]

    subj_id = BOOK_TO_SUBJECT.get(book_id)
    if not subj_id:
        return []

    dataset, _items = load_oral_focus()
    subject = next((s for s in dataset.get("subjects", []) if s["id"] == subj_id), None)
    if not subject:
        return []

    clean_title = chapter_title.strip()
    alias_target = CHAPTER_ALIASES.get((book_id, clean_title))
    target_norm = normalize_chapter_title(alias_target or clean_title)

    if not target_norm:
        return []

    matched_items: list[dict] = []
    for ch in subject.get("chapters", []):
        ch_title = ch.get("title", "")
        ch_norm = normalize_chapter_title(ch_title)
        if not ch_norm:
            continue

        if alias_target:
            if ch_title == alias_target or normalize_chapter_title(ch_title) == normalize_chapter_title(alias_target):
                matched_items.extend(ch.get("items", []))
        elif ch_norm == target_norm or ch_norm in target_norm or target_norm in ch_norm:
            matched_items.extend(ch.get("items", []))

    seen: set[str] = set()
    result: list[dict] = []
    for item in matched_items:
        item_id = str(item.get("id") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(
            {
                "id": item_id,
                "type": item.get("type", "definition"),
                "type_label": "名词解释" if item.get("type") == "definition" else "简答论述",
                "prompt": str(item.get("title") or item.get("source_title_raw") or ""),
                "source_title_raw": str(item.get("source_title_raw") or item.get("title") or ""),
                "star_level": int(item.get("star_level") or 1),
                "order": int(item.get("order") or len(result) + 1),
                "answer_markdown": str(item.get("answer_markdown") or ""),
                "character_count": int(item.get("character_count") or len(str(item.get("answer_markdown") or ""))),
                "has_table": bool(item.get("has_table", False)),
            }
        )

    _MAPPING_CACHE[cache_key] = result
    return result


def clear_chapter_questions_cache() -> None:
    """Clear internal mapping cache."""
    _MAPPING_CACHE.clear()
