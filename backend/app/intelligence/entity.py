"""
Entity Resolution — Name matching, deduplication, identity confidence scoring.

Handles:
  - Fuzzy name matching across different transliterations
  - Hebrew/Arabic/English name variants
  - Location-based disambiguation (same name, different person)
  - Confidence scoring for identity resolution
"""

import re
from difflib import SequenceMatcher
from typing import Optional


def normalize_name(name: str) -> str:
    """Normalize a name for comparison: lowercase, strip titles, deduplicate spaces."""
    name = name.strip()
    # Remove common titles
    titles = [
        "mr", "mrs", "ms", "dr", "prof", "rav", "rabbi", "sheikh",
        "מר", "גב'", "ד'ר", "פרופ", "הרב", "שייח",
    ]
    for title in titles:
        name = re.sub(rf'\b{title}\b\.?\s*', '', name, flags=re.IGNORECASE)

    name = re.sub(r'\s+', ' ', name).strip().lower()
    return name


def name_similarity(name1: str, name2: str) -> float:
    """
    Calculate similarity between two names (0-1).
    Handles transliteration differences.
    """
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)

    # Exact match
    if n1 == n2:
        return 1.0

    # Sequence similarity
    seq_sim = SequenceMatcher(None, n1, n2).ratio()

    # Word-level matching (names can be in different orders)
    words1 = set(n1.split())
    words2 = set(n2.split())
    if words1 and words2:
        word_overlap = len(words1 & words2) / max(len(words1), len(words2))
        # Weighted: sequence 40%, word overlap 60%
        return seq_sim * 0.4 + word_overlap * 0.6

    return seq_sim


def resolve_entity(
    name: str,
    location: str = "",
    candidate_pool: list[dict] | None = None,
    threshold: float = 0.75,
) -> dict:
    """
    Resolve a person name against a candidate pool.
    Returns best match with confidence score.

    Args:
        name: Person name to resolve
        location: Location for disambiguation
        candidate_pool: List of candidate entities with 'name' and optionally 'location'
        threshold: Minimum similarity to consider a match

    Returns:
        {matched: bool, entity: dict|None, confidence: float, alternatives: list}
    """
    result = {
        "matched": False,
        "entity": None,
        "confidence": 0.0,
        "alternatives": [],
    }

    if not candidate_pool:
        return result

    best_match = None
    best_score = 0.0

    for candidate in candidate_pool:
        c_name = candidate.get("name", "")
        c_location = candidate.get("location", "")

        name_sim = name_similarity(name, c_name)
        location_bonus = 0.0

        if location and c_location and location.lower() == c_location.lower():
            location_bonus = 0.15

        combined = name_sim + location_bonus

        if combined > best_score:
            best_score = combined
            best_match = candidate

        if combined > 0.5:
            result["alternatives"].append({
                "entity": candidate,
                "similarity": round(combined, 3),
            })

    if best_score >= threshold and best_match:
        result["matched"] = True
        result["entity"] = best_match
        result["confidence"] = round(min(best_score, 1.0), 3)

    # Sort alternatives by similarity
    result["alternatives"].sort(key=lambda x: x["similarity"], reverse=True)
    result["alternatives"] = result["alternatives"][:5]

    return result


# Hebrew/English transliteration helpers

HEBREW_TO_ENGLISH = {
    'א': 'a', 'ב': 'b', 'ג': 'g', 'ד': 'd', 'ה': 'h', 'ו': 'v',
    'ז': 'z', 'ח': 'ch', 'ט': 't', 'י': 'y', 'כ': 'k', 'ך': 'ch',
    'ל': 'l', 'מ': 'm', 'ם': 'm', 'נ': 'n', 'ן': 'n', 'ס': 's',
    'ע': 'a', 'פ': 'p', 'ף': 'f', 'צ': 'tz', 'ץ': 'tz', 'ק': 'k',
    'ר': 'r', 'ש': 'sh', 'ת': 't',
}


def hebrew_to_latin_approximation(hebrew_name: str) -> str:
    """Generate approximate Latin transliteration of Hebrew name."""
    result = []
    for char in hebrew_name:
        if char in HEBREW_TO_ENGLISH:
            result.append(HEBREW_TO_ENGLISH[char])
        elif char == ' ':
            result.append(' ')
    return ''.join(result).strip()


def generate_name_variants(name: str) -> list[str]:
    """
    Generate common transliteration variants of a name.
    E.g., "ישראל ישראלי" → ["Yisrael Yisraeli", "Israel Israeli", "Isral Yisrali"]
    """
    variants = [name]

    # Detect if Hebrew
    if any(0x05D0 <= ord(c) <= 0x05EA for c in name):
        latin = hebrew_to_latin_approximation(name)
        variants.append(latin)
        # Common variant: Y→I, double letters simplification
        variants.append(latin.replace('yy', 'y').replace('tt', 't'))
        variants.append(latin.replace('y', 'i').replace('ch', 'h'))

    # Detect if Arabic
    if any(0x0600 <= ord(c) <= 0x06FF for c in name):
        # Arabic transliteration varies widely — basic simplification
        latin_ar = name  # Simplified — real impl would use a library
        variants.append(latin_ar)

    return list(set(variants))
