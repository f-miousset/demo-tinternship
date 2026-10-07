"""Tests for job title formatting, gender indicator removal, elisions, and redundancy."""

from __future__ import annotations

import pytest

from tinternship_backend.services import docx_template as dt
from tinternship_backend.services import render
from tinternship_backend.services.job_titles import (
    all_caps_words,
    clean_title_dashes,
    format_sentence_elisions_and_redundancies,
    has_gender_indicator,
    normalise_title_casing,
    strip_gender_indicators,
)


class TestStripGenderIndicators:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Stage Développeur (H/F)", "Stage Développeur"),
            ("Stage Développeur (F/H)", "Stage Développeur"),
            ("Ingénieur IA (F/H/X)", "Ingénieur IA"),
            ("Consultant Data [m/w/d]", "Consultant Data"),
            ("Software Engineer (all genders)", "Software Engineer"),
            ("Stage Data Scientist - H/F", "Stage Data Scientist"),
            ("Data Engineer / F/H", "Data Engineer"),
            ("Stage Développeur H/F", "Stage Développeur"),
            ("Stage Développeur F/H", "Stage Développeur"),
            ("Ingénieur IA (Femme/Homme)", "Ingénieur IA"),
            ("Ingénieur IA (H / F)", "Ingénieur IA"),
            ("Data Analyst (m/f/d)", "Data Analyst"),
            ("Expert Sécurité (tous genres)", "Expert Sécurité"),
            ("Ingénieur IA - (F/H)", "Ingénieur IA"),
        ],
    )
    def test_strips_all_common_gender_indicators(self, raw: str, expected: str):
        assert strip_gender_indicators(raw) == expected

    def test_has_gender_indicator_detects_them(self):
        assert has_gender_indicator("Stage Développeur (H/F)") is True
        assert has_gender_indicator("Stage Développeur (F/H)") is True
        assert has_gender_indicator("Data Scientist [m/w/d]") is True
        assert has_gender_indicator("Data Scientist") is False


class TestNormaliseTitleCasing:
    def test_normalises_regular_words_in_all_caps(self):
        assert normalise_title_casing("stagiaire Expert Sécurité DATA") == "stagiaire Expert Sécurité Data"
        assert normalise_title_casing("STAGE CONSULTANT DATA") == "Stage Consultant Data"

    def test_preserves_technical_acronyms(self):
        assert normalise_title_casing("Ingénieur IA") == "Ingénieur IA"
        assert normalise_title_casing("Lead Data Scientist NLP / LLM") == "Lead Data Scientist NLP / LLM"
        assert normalise_title_casing("ML Engineer Cloud AWS & GCP") == "ML Engineer Cloud AWS & GCP"
        assert normalise_title_casing("Architecte RAG et API SQL") == "Architecte RAG et API SQL"
        assert normalise_title_casing("Étudiant UTC") == "Étudiant UTC"

    def test_handles_french_prepositions_in_caps(self):
        assert normalise_title_casing("CONCEPTION D'AGENTS AUTONOMES") == "Conception d'Agents Autonomes"

    def test_finds_all_caps_words(self):
        assert all_caps_words("stagiaire Expert Sécurité DATA") == ["DATA"]
        assert all_caps_words("STAGE CONSULTANT DATA") == ["STAGE", "CONSULTANT", "DATA"]
        assert all_caps_words("Ingénieur IA NLP LLM SQL") == []


class TestCleanTitleDashes:
    def test_transforms_french_dashes_into_natural_connectors(self):
        assert (
            clean_title_dashes("Ingénieur IA - Conception d'agents autonomes", language="fr")
            == "Ingénieur IA pour la conception d'agents autonomes"
        )
        assert (
            clean_title_dashes("Data Scientist - Modélisation prédictive", language="fr")
            == "Data Scientist pour la modélisation prédictive"
        )
        assert (
            clean_title_dashes("Ingénieur - Recherche opérationnelle", language="fr")
            == "Ingénieur en recherche opérationnelle"
        )

    def test_transforms_english_dashes_into_prepositions(self):
        assert (
            clean_title_dashes("Software Engineer - Distributed Systems", language="en")
            == "Software Engineer in distributed systems"
        )


class TestSentenceElisionsAndRedundancies:
    def test_user_example_1(self):
        """Example 1 from user:
        Template: Étudiant en Ingénierie de l'IA à l'Université de Technologie de Lyon (UTL),
        à la recherche d'un stage de fin d'études en tant que [job_title].
        Fill: Ingénieur IA - Conception d'agents autonomes
        Correction: ... en tant qu’Ingénieur IA pour la conception d'agents autonomes.
        """
        prefix = (
            "Étudiant en Ingénierie de l'IA à l'Université de Technologie de Lyon (UTL), "
            "à la recherche d'un stage de fin d'études en tant que "
        )
        fill = "Ingénieur IA - Conception d'agents autonomes"
        new_prefix, new_fill = format_sentence_elisions_and_redundancies(
            prefix, fill, token_name="job_title", language="fr"
        )
        result = new_prefix + new_fill
        expected = (
            "Étudiant en Ingénierie de l'IA à l'Université de Technologie de Lyon (UTL), "
            "à la recherche d'un stage de fin d'études en tant qu'Ingénieur IA pour la conception "
            "d'agents autonomes"
        )
        assert result == expected

    def test_user_example_2(self):
        """Example 2 from user:
        Template: Étudiant en Ingénierie de l'IA à l'Université de Technologie de Lyon (UTL),
        à la recherche d'un stage de fin d'études en tant que [job_title].
        Fill: stagiaire Expert Sécurité DATA
        Correction: ... à la recherche d'un projet de fin d'études en tant que stagiaire Expert Sécurité Data.
        """
        prefix = (
            "Étudiant en Ingénierie de l'IA à l'Université de Technologie de Lyon (UTL), "
            "à la recherche d'un stage de fin d'études en tant que "
        )
        fill = "stagiaire Expert Sécurité DATA"
        new_prefix, new_fill = format_sentence_elisions_and_redundancies(
            prefix, fill, token_name="job_title", language="fr"
        )
        result = new_prefix + new_fill
        expected = (
            "Étudiant en Ingénierie de l'IA à l'Université de Technologie de Lyon (UTL), "
            "à la recherche d'un projet de fin d'études en tant que stagiaire Expert Sécurité Data"
        )
        assert result == expected

    def test_strips_gender_indicators_from_fill(self):
        prefix = "à la recherche d'un stage de fin d'études en tant que "
        fill = "Data Scientist (F/H)"
        new_prefix, new_fill = format_sentence_elisions_and_redundancies(
            prefix, fill, token_name="job_title", language="fr"
        )
        assert new_fill == "Data Scientist"
        assert new_prefix + new_fill == "à la recherche d'un stage de fin d'études en tant que Data Scientist"

    def test_english_a_vs_an_elision(self):
        prefix = "seeking an end-of-studies internship as a "
        _, fill_ai = format_sentence_elisions_and_redundancies(
            prefix, "AI Engineer", token_name="job_title", language="en"
        )
        pref_ai, _ = format_sentence_elisions_and_redundancies(
            prefix, "AI Engineer", token_name="job_title", language="en"
        )
        assert pref_ai + fill_ai == "seeking an end-of-studies internship as an AI Engineer"

        pref_ml, fill_ml = format_sentence_elisions_and_redundancies(
            prefix, "ML Engineer", token_name="job_title", language="en"
        )
        assert pref_ml + fill_ml == "seeking an end-of-studies internship as an ML Engineer"

        pref_ds, fill_ds = format_sentence_elisions_and_redundancies(
            prefix, "Data Scientist", token_name="job_title", language="en"
        )
        assert pref_ds + fill_ds == "seeking an end-of-studies internship as a Data Scientist"

    def test_cover_letter_reference_line_redundant_stage(self):
        prefix = "Objet : Candidature au stage "
        fill = "Stage – Data Scientist (H/F)"
        new_prefix, new_fill = format_sentence_elisions_and_redundancies(
            prefix, fill, token_name="job_posting_name", language="fr"
        )
        assert new_fill == "Data Scientist"
        assert new_prefix + new_fill == "Objet : Candidature au stage Data Scientist"


class TestFilledLinesIntegration:
    def test_filled_lines_applies_elisions_and_redundancy(self):
        line = (
            "Étudiant en Ingénierie de l'IA à l'Université de Technologie de Lyon (UTL), "
            "à la recherche d'un stage de fin d'études en tant que [job_title]. "
            "Spécialisé dans [job_posting_keywords_sentence]."
        )
        from conftest import build_docx

        blocks = dt.read_blocks(build_docx([line]))
        slots = dt.find_slots(blocks)

        # Fill with Example 1
        fills1 = {
            slots[0].key: "Ingénieur IA - Conception d'agents autonomes",
            slots[1].key: "les systèmes multi-agents",
        }
        lines1 = dt.filled_lines(blocks, slots, fills1)
        assert "en tant qu'Ingénieur IA pour la conception d'agents autonomes." in lines1[0]

        # Fill with Example 2
        fills2 = {
            slots[0].key: "stagiaire Expert Sécurité DATA",
            slots[1].key: "la cybersécurité et la conformité",
        }
        lines2 = dt.filled_lines(blocks, slots, fills2)
        expected_phrase = (
            "à la recherche d'un projet de fin d'études en tant que stagiaire Expert Sécurité Data."
        )
        assert expected_phrase in lines2[0]


class TestDocumentStemNoGenderIndicators:
    def test_document_stem_removes_hf_and_fh(self):
        stem = render.document_stem(
            "resume",
            candidate="Alex Martin",
            company="Acme Labs",
            title="Stage Développeur (H/F)",
            language="fr",
        )
        assert "H_F" not in stem
        assert "F_H" not in stem
        assert stem == "CV_Alex_Martin_Acme_Labs_Stage_Développeur"

    def test_document_stem_normalises_all_caps(self):
        stem = render.document_stem(
            "cover_letter",
            candidate="Alex Martin",
            company="Acme Labs",
            title="EXPERT SÉCURITÉ DATA (F/H)",
            language="fr",
        )
        assert "H_F" not in stem
        assert "F_H" not in stem
        assert "EXPERT" not in stem
        assert "DATA" not in stem
        assert "Expert_Sécurité_Data" in stem
