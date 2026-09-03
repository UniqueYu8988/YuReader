"""Cross-domain unified search module for YuReader."""

from __future__ import annotations

import re
from yureader.catalog import catalog
from yureader.practice import question_bank_catalog, load_bank_questions
from yureader.oral_focus import load_oral_focus


def global_search(query: str, category: str = "") -> dict:
    q = (query or "").strip().lower()
    if not q:
        return {"total": 0, "results": []}

    results: list[dict] = []
    
    # 1. Books & Sections
    if not category or category == "books":
        try:
            books, sections = catalog()
            for s_id, section in sections.items():
                title = section.get("title", "")
                chapter_title = section.get("chapter_title", "")
                content_preview = section.get("content", "") or ""
                
                score = 0
                if q in title.lower():
                    score += 10
                if q in chapter_title.lower():
                    score += 5
                if q in content_preview.lower():
                    score += 2
                    
                if score > 0:
                    book_title = section.get("book_title") or "教材"
                    results.append({
                        "type": "book",
                        "category_label": "教材原文",
                        "icon": "book-open",
                        "title": f"《{book_title}》· {title}",
                        "subtitle": f"{chapter_title} · {section.get('character_count', 0)} 字",
                        "snippet": extract_snippet(content_preview or title, q),
                        "score": score,
                        "target": {"view": "reader", "section_id": s_id, "book_id": section.get("book_id", "")},
                    })
        except Exception:
            pass

    # 2. Oral Medicine Focus
    if not category or category == "oral":
        try:
            _, oral_items = load_oral_focus()
            for item_id, item in oral_items.items():
                title = item.get("title", "")
                answer = item.get("answer_markdown", "") or ""
                translation = item.get("definition_translation", "") or ""
                
                score = 0
                if q in title.lower():
                    score += 12
                if q in translation.lower():
                    score += 8
                if q in answer.lower():
                    score += 3
                    
                if score > 0:
                    type_label = "名词解释" if item.get("type") == "definition" else "简答论述"
                    subj = item.get("subject", {}).get("title") or "口腔医学"
                    results.append({
                        "type": "oral",
                        "category_label": f"口腔重点 · {type_label}",
                        "icon": "stethoscope",
                        "title": f"[{type_label}] {title}",
                        "subtitle": f"{subj} · 重点考点",
                        "snippet": extract_snippet(answer or translation or title, q),
                        "score": score,
                        "target": {"view": "oral_focus", "item_id": item_id},
                    })
        except Exception:
            pass

    # 3. Practice Question Banks
    if not category or category == "practice":
        try:
            all_banks = question_bank_catalog()
            for bank in all_banks:
                bank_title = bank.get("title", bank.get("id"))
                domain = bank.get("domain", "politics")
                try:
                    questions = load_bank_questions(bank["id"])
                except Exception:
                    continue
                for item in questions:
                    stem = item.get("stem_md", "")
                    analysis = item.get("source_analysis_md", "") or ""
                    
                    score = 0
                    if q in stem.lower():
                        score += 8
                    if q in analysis.lower():
                        score += 2
                        
                    if score > 0:
                        domain_label = "政治理论" if domain == "politics" else "考研英语"
                        results.append({
                            "type": "practice",
                            "category_label": f"{domain_label}真题",
                            "icon": "check-square",
                            "title": f"[{domain_label}] {stem[:45]}...",
                            "subtitle": bank_title,
                            "snippet": extract_snippet(stem, q),
                            "score": score,
                            "target": {"view": "practice", "resource_id": bank["id"], "question_id": item.get("question_id")},
                        })
        except Exception:
            pass

    # Sort results by score desc
    results.sort(key=lambda x: x["score"], reverse=True)
    top_results = results[:25]

    return {
        "total": len(results),
        "results": top_results,
    }


def extract_snippet(text: str, query: str, window: int = 70) -> str:
    cleaned = re.sub(r"[#*`>\-\[\]]", " ", text)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return ""
    pos = cleaned.lower().find(query.lower())
    if pos == -1:
        return cleaned[:window] + "..." if len(cleaned) > window else cleaned
    start = max(0, pos - window // 2)
    end = min(len(cleaned), pos + len(query) + window // 2)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(cleaned) else ""
    return prefix + cleaned[start:end] + suffix
