"""Deterministic question clarification that never blocks a run."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from autoresearcher.models import Clarification

_INTEREST_KEYWORDS = {
    "food": ("food", "restaurant", "cuisine", "eat"),
    "culture": ("culture", "museum", "history", "heritage", "temple"),
    "nature": ("nature", "beach", "park", "hike", "wildlife"),
    "shopping": ("shopping", "market", "souvenir"),
    "nightlife": ("nightlife", "bar", "club"),
    "business": ("market research", "industry", "competitor", "business"),
}


def _infer_location(question: str) -> str | None:
    patterns = (
        r"^(?:plan\s+)?(?:a\s+)?(.+?)\s+(?:trip|itinerary)\b",
        r"\b(?:trip|travel)\s+to\s+(.+?)(?:\s+for\b|\s+in\b|$)",
        r"\bvisit\s+(.+?)(?:\s+for\b|\s+in\b|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if match:
            location = match.group(1).strip(" ,.-")
            if 2 <= len(location) <= 200:
                return location
    return None


def _infer_start_date(question: str) -> date | None:
    """Parse only complete, explicitly written dates; never invent a year."""
    month = (
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)"
    )
    candidates = [
        (r"\b\d{4}-\d{1,2}-\d{1,2}\b", ("%Y-%m-%d",)),
        (r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b", ("%d/%m/%Y", "%d-%m-%Y")),
        (
            rf"\b{month}\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+\d{{4}}\b",
            ("%B %d %Y", "%b %d %Y"),
        ),
        (
            rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{month}\s+\d{{4}}\b",
            ("%d %B %Y", "%d %b %Y"),
        ),
    ]
    for pattern, formats in candidates:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if match is None:
            continue
        value = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", match.group(0), flags=re.I)
        value = value.replace(",", "")
        for date_format in formats:
            try:
                return datetime.strptime(value, date_format).date()
            except ValueError:
                continue
    return None


def clarify_question(question: str) -> Clarification:
    """Infer common scope fields and record transparent defaults as assumptions."""
    normalized = " ".join(question.split())
    lowered = normalized.lower()
    trip_like = any(word in lowered for word in ("trip", "travel", "visit", "itinerary"))
    location = _infer_location(normalized) if trip_like else None
    start_date = _infer_start_date(normalized) if trip_like else None

    day_match = re.search(r"\b(\d{1,3})\s*[- ]?days?\b", lowered)
    days = int(day_match.group(1)) if day_match else None
    assumptions: list[str] = []
    if trip_like and days is None:
        days = 3
        assumptions.append("Trip duration was not specified; a three-day trip is assumed.")
    if trip_like and start_date is None:
        assumptions.append(
            "No travel date was provided; the live forecast starts on the report date and "
            "does not set itinerary dates."
        )

    if any(word in lowered for word in ("cheap", "budget", "affordable")):
        budget: Literal["budget", "mid-range", "luxury", "unspecified"] = "budget"
    elif any(word in lowered for word in ("luxury", "premium", "five-star")):
        budget = "luxury"
    elif any(word in lowered for word in ("mid-range", "moderate", "comfortable")):
        budget = "mid-range"
    else:
        budget = "unspecified"
        if trip_like:
            assumptions.append("No budget tier was specified; options should cover multiple tiers.")

    interests = [
        interest
        for interest, keywords in _INTEREST_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    if trip_like and not interests:
        interests = ["major attractions", "local food", "practical logistics"]
        assumptions.append(
            "No interests were specified; a balanced first-time-visitor mix is assumed."
        )
    elif not trip_like and not interests:
        interests = ["general research coverage"]

    return Clarification(
        days=days,
        location=location,
        start_date=start_date,
        budget=budget,
        interests=interests,
        assumptions=assumptions,
    )
