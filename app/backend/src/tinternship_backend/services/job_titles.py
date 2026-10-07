"""Job title and sentence formatting for generated resumes, letters, and file names.

This module enforces sentence flow, French grammar (elisions, redundancy),
casing normalization, and strips recruitment boilerplate such as gender
indicators `(F/H)` or `(H/F)`.

Rules enforced here:
1. **Remove gender indicators**: `(F/H)`, `(H/F)`, `(M/F)`, `(m/w/d)`, `(all genders)`,
   etc. must never appear in resume headers, cover letters, or file names.
2. **Normalize ALL CAPS words**: Normal words written in all caps in job postings
   (e.g. `DATA` -> `Data`, `STAGE` -> `Stage`) are converted to proper case,
   while preserving recognized technical acronyms (`IA`, `AI`, `ML`, `NLP`, `SQL`, etc.).
3. **Natural sentence flow**: Formulaic dashes/hyphens from raw titles
   (`Ingénieur IA - Conception d'agents autonomes`) become natural grammatical connectors
   (`Ingénieur IA pour la conception d'agents autonomes`).
4. **French elision**: `en tant que ` preceding a vowel or mute H elides to `en tant qu'`.
5. **Redundancy elimination**: `stage de fin d'études` followed by `stagiaire` becomes
   `projet de fin d'études`.
6. **English elision**: `as a ` preceding a vowel sound becomes `as an `.
"""

from __future__ import annotations

import re

# Technical and industry acronyms that should remain capitalized.
TECHNICAL_ACRONYMS = frozenset(
    {
        "AI",
        "API",
        "APIS",
        "ASIC",
        "AWS",
        "B2B",
        "B2C",
        "BI",
        "CD",
        "CEO",
        "CI",
        "CNIL",
        "CNRS",
        "CPU",
        "CRM",
        "CUDA",
        "CTO",
        "DL",
        "ERP",
        "ETL",
        "FPGA",
        "GCP",
        "GDPR",
        "GPU",
        "HR",
        "HTML",
        "HTTP",
        "IA",
        "IOT",
        "IT",
        "JSON",
        "KPI",
        "LLM",
        "LLMOPS",
        "LLMS",
        "ML",
        "MLOPS",
        "NLP",
        "OECD",
        "OS",
        "PM",
        "PO",
        "QA",
        "RAG",
        "REST",
        "RGPD",
        "RH",
        "RSSI",
        "SAAS",
        "PAAS",
        "IAAS",
        "SAP",
        "SDK",
        "SEA",
        "SEO",
        "SI",
        "SIRENE",
        "SQL",
        "SRE",
        "TPU",
        "UI",
        "UTC",
        "UX",
    }
)

# Standard acronym casing overrides where mixed casing is standard.
ACRONYM_CASING: dict[str, str] = {
    "MLOPS": "MLOps",
    "LLMOPS": "LLMOps",
    "DEVOPS": "DevOps",
    "SAAS": "SaaS",
    "PAAS": "PaaS",
    "IAAS": "IaaS",
}

# Regex patterns matching gender indicators in all common formats.
_GENDER_INDICATOR_PATTERNS = [
    # Bracketed/parenthesized: (F/H), (H/F), [m/w/d], (all genders), (Femme/Homme), etc.
    re.compile(
        r"\s*[\(\[\{]\s*(?:"
        r"f\s*/\s*h(?:\s*/\s*[xd])?|"
        r"h\s*/\s*f(?:\s*/\s*[xd])?|"
        r"m\s*/\s*f(?:\s*/\s*[xd])?|"
        r"f\s*/\s*m(?:\s*/\s*[xd])?|"
        r"m\s*/\s*w\s*/\s*d|"
        r"w\s*/\s*m\s*/\s*d|"
        r"d\s*/\s*m\s*/\s*w|"
        r"d\s*/\s*w\s*/\s*m|"
        r"all\s+genders?|"
        r"tous\s+genres?|"
        r"femmes?\s*/\s*hommes?|"
        r"hommes?\s*/\s*femmes?"
        r")\s*[\)\]\}]",
        re.IGNORECASE,
    ),
    # After a separator like -, –, —, /, |: e.g. " - H/F", " / F/H", " | M/F"
    re.compile(
        r"\s*[-–—/|]\s*(?:"
        r"f\s*/\s*h(?:\s*/\s*[xd])?|"
        r"h\s*/\s*f(?:\s*/\s*[xd])?|"
        r"m\s*/\s*f(?:\s*/\s*[xd])?|"
        r"f\s*/\s*m(?:\s*/\s*[xd])?|"
        r"m\s*/\s*w\s*/\s*d|"
        r"w\s*/\s*m\s*/\s*d"
        r")\b",
        re.IGNORECASE,
    ),
    # Standalone suffix or token: " Stage Développeur H/F", " Ingénieur F/H "
    re.compile(
        r"(?<=\s)(?:"
        r"f\s*/\s*h(?:\s*/\s*[xd])?|"
        r"h\s*/\s*f(?:\s*/\s*[xd])?|"
        r"m\s*/\s*f(?:\s*/\s*[xd])?|"
        r"f\s*/\s*m(?:\s*/\s*[xd])?|"
        r"m\s*/\s*w\s*/\s*d|"
        r"w\s*/\s*m\s*/\s*d"
        r")(?=\s|$|[.,;!])",
        re.IGNORECASE,
    ),
]

_VOWELS = frozenset("aeiouyàâäéèêëîïôöùûü")

# Letters whose English names start with a vowel sound:
# A ("ay"), E ("ee"), F ("ef"), H ("aitch"), I ("eye"), L ("el"), M ("em"),
# N ("en"), O ("oh"), R ("ar"), S ("es"), X ("ex").
_ENGLISH_VOWEL_SOUND_INITIALS = frozenset("aefhilmnorsx")


def field_name(token: str) -> str:
    """The name inside a placeholder, normalised: `[Company Name]` -> `company_name`."""
    inner = token.strip().strip("[]{}<>").strip()
    return re.sub(r"[^a-z0-9]+", "_", inner.lower()).strip("_")


def strip_gender_indicators(text: str) -> str:
    """Remove (F/H), (H/F), (M/F), (m/w/d), (all genders) and variants."""
    result = text
    for pattern in _GENDER_INDICATOR_PATTERNS:
        result = pattern.sub("", result)
    # Clean up any dangling punctuation or whitespace left at edges
    result = re.sub(r"\s+", " ", result).strip()
    result = re.sub(r"[\s\-–—/|:,;]+$", "", result).strip()
    result = re.sub(r"^[\s\-–—/|:,;]+", "", result).strip()
    return result


def has_gender_indicator(text: str) -> bool:
    """True if text contains an unstripped gender indicator."""
    return any(pattern.search(text) is not None for pattern in _GENDER_INDICATOR_PATTERNS)


def _normalise_single_word(word: str) -> str:
    """Convert an all-caps word to titlecase unless it is a recognized acronym."""
    # Check if inside parentheses or punctuation
    prefix = ""
    suffix = ""
    while word and not word[0].isalnum():
        prefix += word[0]
        word = word[1:]
    while word and not word[-1].isalnum():
        suffix = word[-1] + suffix
        word = word[:-1]

    if not word:
        return prefix + suffix

    upper = word.upper()
    if upper in ACRONYM_CASING:
        core = ACRONYM_CASING[upper]
    elif upper in TECHNICAL_ACRONYMS:
        core = upper
    elif word.isupper() and len(word) >= 1:
        # Common lowercase French prepositions/articles typed in caps
        if upper in {"D", "L", "DE", "DU", "DES", "LE", "LA", "LES", "EN", "AU", "AUX", "ET", "POUR", "SUR"}:
            core = word.lower()
        else:
            core = word.capitalize()
    else:
        core = word

    return prefix + core + suffix


def normalise_title_casing(text: str) -> str:
    """Normalize words written in ALL CAPS (e.g. `DATA` -> `Data`), preserving acronyms."""
    tokens = text.split()
    normalised = []
    for token in tokens:
        # Handle hyphenated or apostrophed tokens like "D'AGENTS" or "SÉCURITÉ-DATA"
        parts = re.split(r"([’'\-])", token)
        normalised_token = "".join(_normalise_single_word(p) for p in parts)
        normalised.append(normalised_token)
    return " ".join(normalised)


def all_caps_words(text: str) -> list[str]:
    """Find words of 4+ characters written in all-caps that are not technical acronyms."""
    words: list[str] = []
    for raw in re.findall(r"\b[A-ZÀ-ÖØ-ß]{4,}\b", text):
        upper = raw.upper()
        if upper not in TECHNICAL_ACRONYMS and upper not in ACRONYM_CASING:
            words.append(raw)
    return words


# Common French nouns following a dash in job titles, with their natural article.
_FRENCH_NOUN_CONNECTORS: dict[str, str] = {
    # feminine: "pour la conception d'agents autonomes"
    "conception": "pour la conception",
    "création": "pour la création",
    "modélisation": "pour la modélisation",
    "gestion": "pour la gestion",
    "mise en place": "pour la mise en place",
    "réalisation": "pour la réalisation",
    "recherche": "en recherche",
    "vision": "en vision",
    "qualification": "pour la qualification",
    # masculine: "pour le développement de..."
    "développement": "pour le développement",
    "déploiement": "pour le déploiement",
    "traitement": "pour le traitement",
    "pilotage": "pour le pilotage",
    "suivi": "pour le suivi",
    "design": "pour le design",
    "management": "pour le management",
    # vowel: "pour l'optimisation de..."
    "analyse": "pour l'analyse",
    "optimisation": "pour l'optimisation",
    "évaluation": "pour l'évaluation",
    "automatisation": "pour l'automatisation",
    "intégration": "pour l'intégration",
    "architecture": "pour l'architecture",
    "implémentation": "pour l'implémentation",
    "amélioration": "pour l'amélioration",
}


def clean_title_dashes(text: str, language: str = "fr") -> str:
    """Transform formulaic title dashes into natural grammatical prepositions in sentences."""
    if language == "fr":
        match = re.search(r"\s+[-–—]\s+", text)
        if match:
            prefix = text[: match.start()]
            after_dash = text[match.end() :]
            lower_after = after_dash.lower()
            for noun, connector in _FRENCH_NOUN_CONNECTORS.items():
                if lower_after.startswith(noun):
                    remainder = after_dash[len(noun) :]
                    return f"{prefix} {connector}{remainder}"
            # Fallback if unknown: if first word is capitalized and not acronym
            first_word_match = re.match(r"^[A-Za-zÀ-ÿ]+", after_dash)
            if first_word_match:
                first_word = first_word_match.group(0)
                if first_word[0].isupper() and first_word.upper() not in TECHNICAL_ACRONYMS:
                    lower_word = first_word[0].lower() + first_word[1:]
                    remainder = after_dash[len(first_word) :]
                    return f"{prefix} pour {lower_word}{remainder}"
    elif language == "en":
        match = re.search(r"\s+[-–—]\s+", text)
        if match:
            prefix = text[: match.start()]
            after_dash = text[match.end() :].strip()
            words = after_dash.split()
            cleaned_words = [
                w if w.upper() in TECHNICAL_ACRONYMS or w.upper() in ACRONYM_CASING else w.lower()
                for w in words
            ]
            lower_phrase = " ".join(cleaned_words)
            return f"{prefix} in {lower_phrase}"

    return text


def clean_job_title(title: str, language: str = "fr") -> str:
    """Full title cleaning: remove gender indicators, normalize all-caps words, clean dashes."""
    cleaned = strip_gender_indicators(title)
    cleaned = normalise_title_casing(cleaned)
    return cleaned


def clean_job_posting_name(text: str, prefix_context: str = "", language: str = "fr") -> str:
    """Clean a job posting name for cover letter reference lines.

    Strips gender indicators, normalizes casing, and removes redundant 'Stage'
    if the preceding line already contains 'Candidature au stage'.
    """
    cleaned = clean_job_title(text, language=language)
    if re.search(r"stage\b", prefix_context, re.IGNORECASE):
        # Strip leading "Stage" or "Stage – "
        cleaned = re.sub(r"^\s*stage\s*[-–—:]*\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.strip(" -–—:/|")


def starts_with_vowel(text: str) -> bool:
    """True if text begins with a vowel or mute H in French."""
    trimmed = text.strip()
    if not trimmed:
        return False
    first = trimmed[0].lower()
    if first in _VOWELS:
        return True
    # French mute H
    if first == "h" and len(trimmed) > 1 and trimmed[1].lower() in _VOWELS:
        # Common tech titles with mute H
        return True
    return False


def starts_with_english_vowel_sound(text: str) -> bool:
    """True if text begins with a vowel sound in English."""
    trimmed = text.strip()
    if not trimmed:
        return False
    first_word = trimmed.split()[0]
    first_word_clean = re.sub(r"[^a-zA-Z]", "", first_word)
    if not first_word_clean:
        return False

    # Acronyms pronounced letter-by-letter
    if first_word_clean.isupper():
        return first_word_clean[0].lower() in _ENGLISH_VOWEL_SOUND_INITIALS

    # Regular words: initial vowel except words starting with "eu" or "uni-" (e.g. "user", "unique")
    lower = first_word_clean.lower()
    if lower.startswith(("uni", "use", "user", "one", "euro", "eu")):
        return False
    return lower[0] in "aeiou"


def format_sentence_elisions_and_redundancies(
    line_prefix: str,
    fill_text: str,
    token_name: str,
    language: str = "fr",
) -> tuple[str, str]:
    """Adjust line prefix and fill text so the joined sentence is grammatically seamless.

    - If French and fill contains 'stagiaire', changes 'stage de fin d'études'
      to 'projet de fin d'études'.
    - If French and preceding ends with 'en tant que ' before a vowel, elides to 'en tant qu''.
    - If English and preceding ends with 'as a ' before a vowel sound, changes to 'as an '.
    - If cover letter prefix has 'stage', strips leading 'Stage' from fill.
    """
    new_prefix = line_prefix
    new_fill = fill_text

    # 1. Clean gender indicators and normalize all-caps words in the fill
    new_fill = strip_gender_indicators(new_fill)
    if token_name in {"job_title", "job_posting_name"}:
        new_fill = normalise_title_casing(new_fill)

    # 2. Cover letter reference line: strip redundant "Stage"
    if token_name == "job_posting_name":
        if re.search(r"stage\s*$", new_prefix, re.IGNORECASE) or re.search(
            r"au stage\b", new_prefix, re.IGNORECASE
        ):
            new_fill = re.sub(r"^\s*stage\s*[-–—:]*\s*", "", new_fill, flags=re.IGNORECASE).strip()
        new_fill = new_fill.strip(" -–—:/|")

    # 3. Resume header: redundant "stage" vs "stagiaire"
    if token_name == "job_title":
        # Transform dashes into natural connectors in the fill
        new_fill = clean_title_dashes(new_fill, language=language)

        if re.search(r"\bstagiaire\b", new_fill, re.IGNORECASE):
            # Change "stage de fin d'études" -> "projet de fin d'études"
            new_prefix = re.sub(
                r"stage\s+de\s+fin\s+d['’]études",
                "projet de fin d'études",
                new_prefix,
                flags=re.IGNORECASE,
            )

        # 4. French elision: "en tant que " + vowel -> "en tant qu'"
        if new_prefix.endswith("en tant que "):
            if new_fill.startswith(("qu'", "qu’")):
                # The fill already carried "qu'..."
                new_prefix = new_prefix[:-4]  # leaves "en tant "
            elif new_fill.startswith(("en tant qu'", "en tant qu’", "en tant que ")):
                new_prefix = new_prefix[:-12]
            elif starts_with_vowel(new_fill):
                # Elide "en tant que " -> "en tant qu'"
                # Use curly apostrophe if the prefix uses curly apostrophe, else straight
                apostrophe = "’" if "’" in new_prefix else "'"
                new_prefix = new_prefix[:-4] + "qu" + apostrophe

        # 5. English elision: "as a " + vowel sound -> "as an "
        if new_prefix.endswith("as a "):
            if starts_with_english_vowel_sound(new_fill):
                new_prefix = new_prefix[:-2] + "an "

    return new_prefix, new_fill
