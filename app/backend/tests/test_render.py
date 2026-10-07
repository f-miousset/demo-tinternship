"""Rendering an artifact: the cover letter, and the résumés history still holds.

Two different subjects live here since 2026-08-28.

The **cover letter** is still written by an agent and laid out by this module,
so its HTML preview and its .docx download are both this module's work.

A **résumé** is not. It is the candidate's own .docx with a few lines re-worded
(`tests/test_docx_template.py` covers that), and the only thing `render` still
does for it is name the file. What is tested here is the *legacy* path: the
artifacts generated before the change, into the Harvard template, which are
never migrated and still have to open. Everything about the one-page fit went
with the design that needed it — nothing lays out a page any more, so nothing
can overflow one.
"""

from __future__ import annotations

import pytest

from tinternship_backend.services import render

RESUME = {
    "full_name": "Alex Martin",
    "contact": ["alex@example.com", "Paris", "github.com/example"],
    "education": [
        {
            "institution": "INSA Lyon",
            "location": "Lyon, France",
            "degree": "Engineering degree, Computer Science",
            "end_date": "2028",
            "coursework": ["Machine Learning", "Distributed Systems"],
        }
    ],
    "experiences": [
        {
            "title": "Software Intern",
            "organisation": "Acme",
            "location": "Paris",
            "start_date": "Jun 2025",
            "end_date": "Sep 2025",
            "bullets": [
                {"text": "Built an ingest pipeline handling 2M rows/day", "evidence": "profile"},
                {"text": "Cut deploy time from 20 to 4 minutes", "evidence": "profile"},
            ],
        }
    ],
    "projects": [
        {
            "title": "Retrieval benchmark",
            "location": "",
            "bullets": [{"text": "Compared five sparse retrievers on 1M documents", "evidence": "profile"}],
        }
    ],
    "leadership": [
        {
            "organisation": "Robotics club",
            "title": "Treasurer",
            "location": "Lyon",
            "start_date": "2024",
            "end_date": "2025",
            "bullets": [],
        }
    ],
    "skills": [{"heading": "Technical", "entries": ["Python", "TypeScript"]}],
    "extra_sections": [{"heading": "Awards", "entries": ["Hackathon winner 2025"]}],
    "language": "en",
}

LETTER = {
    "recipient": "Hiring team",
    "subject": "ML internship application",
    "greeting": "Bonjour,",
    "hook": "Your work on sparse retrieval is why I am writing.",
    "fit": "I have shipped retrieval systems at small scale.",
    "evidence": "At Acme I built an ingest pipeline handling 2M rows/day.",
    "motivation": "I want to work where evaluation is taken seriously.",
    "close": "I would welcome a conversation.",
    "signature": "Alex Martin",
    "language": "en",
}


class TestLegacyHtml:
    """Artifacts from before 2026-08-28 must still open, unchanged."""

    def test_resume_html_contains_every_section(self):
        markup = render.legacy_resume_to_html(RESUME)
        for expected in (
            "Alex Martin",
            "alex@example.com",
            "INSA Lyon",
            "Relevant Coursework",
            "Machine Learning",
            "Software Intern",
            "Acme",
            "2M rows/day",
            "Retrieval benchmark",
            "Robotics club",
            "Technical",
            "TypeScript",
            "Awards",
        ):
            assert expected in markup, expected

    def test_sections_follow_the_template_order(self):
        markup = render.legacy_resume_to_html(RESUME)
        order = [
            markup.index(">Education<"),
            markup.index(">Experience<"),
            markup.index(">Projects<"),
            markup.index("Leadership &amp; Activities"),
            markup.index("Skills &amp; Interests"),
        ]
        assert order == sorted(order)

    def test_the_template_has_no_summary_or_headline(self):
        markup = render.legacy_resume_to_html(
            {**RESUME, "summary": "Ambitious student", "headline": "ML Engineer"}
        )
        assert "Ambitious student" not in markup
        assert "ML Engineer" not in markup

    def test_french_uses_french_headings(self):
        markup = render.legacy_resume_to_html({**RESUME, "language": "fr"})
        assert "Formation" in markup
        assert "Expérience professionnelle" in markup
        assert "Cours suivis" in markup
        assert ">Education<" not in markup

    def test_unknown_language_falls_back_to_english(self):
        markup = render.legacy_resume_to_html({**RESUME, "language": "de"})
        assert ">Education<" in markup

    def test_legacy_education_strings_still_render(self):
        markup = render.legacy_resume_to_html({**RESUME, "education": ["INSA Lyon — 2023–2028"]})
        assert "INSA Lyon — 2023–2028" in markup

    def test_html_escapes_user_content(self):
        markup = render.legacy_resume_to_html({**RESUME, "full_name": "<script>alert(1)</script>"})
        assert "<script>alert(1)</script>" not in markup
        assert "&lt;script&gt;" in markup

    def test_cover_letter_renders_paragraphs_in_order(self):
        """A letter generated before 2026-09-09, in the nine-field shape this
        module used to lay out. Rows are never migrated, so opening one still
        has to show what was produced for it."""
        markup = render.legacy_cover_letter_to_html(LETTER)
        hook = markup.index("sparse retrieval")
        close = markup.index("welcome a conversation")
        assert hook < close

    def test_empty_resume_still_renders(self):
        markup = render.legacy_resume_to_html({})
        assert "<html" in markup

    def test_unknown_kind_is_rejected(self):
        try:
            render.render_artifact("plan", RESUME)
        except ValueError as exc:
            assert "No HTML renderer" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("plan should have no HTML renderer")


class TestDocx:
    def test_legacy_resume_docx_is_a_valid_zip_container(self):
        data = render.legacy_resume_to_docx(RESUME)
        assert data[:2] == b"PK"
        assert len(data) > 1000

    def test_legacy_resume_docx_uses_the_template_page_setup(self):
        import io

        from docx import Document
        from docx.shared import Inches

        document = Document(io.BytesIO(render.legacy_resume_to_docx(RESUME)))
        section = document.sections[0]
        # Word stores these in twips, so a round-trip lands within half a twip.
        assert abs(section.page_width - Inches(render.PAGE_WIDTH_IN)) < 635
        assert abs(section.left_margin - Inches(render.MARGIN_SIDE_IN)) < 635
        assert document.styles["Normal"].font.name == "Calibri"

    def test_legacy_resume_docx_carries_the_french_headings(self):
        import io

        from docx import Document

        document = Document(io.BytesIO(render.legacy_resume_to_docx({**RESUME, "language": "fr"})))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        assert "Formation" in text
        assert "Expérience professionnelle" in text

    def test_cover_letter_docx_is_produced(self):
        assert render.legacy_cover_letter_to_docx(LETTER)[:2] == b"PK"


class TestExport:
    """Everything exports as .docx now, on every machine.

    Until 2026-08-28 this produced a PDF when WeasyPrint could load and silently
    fell back to .docx when it could not, which meant the *format* of the
    document an employer received depended on whether Pango happened to be
    installed where the export ran. There is no branch left to take.
    """

    def test_export_writes_a_docx_and_reports_its_mime(self):
        path, mime = render.export_artifact("cover_letter", LETTER, stem="test letter/../v1")

        assert path.exists()
        assert path.suffix == ".docx"
        assert path.read_bytes()[:2] == b"PK"
        assert mime.endswith("wordprocessingml.document")

    def test_the_stem_is_sanitised(self):
        path, _mime = render.export_artifact("cover_letter", LETTER, stem="test letter/../v1")

        assert "/" not in path.name
        assert " " not in path.name

    def test_a_legacy_resume_still_exports(self):
        """The Download button on a pre-change artifact must hand back a file."""
        path, mime = render.export_artifact("resume", RESUME, stem="legacy")

        assert path.suffix == ".docx"
        assert mime.endswith("wordprocessingml.document")


class TestTailoredPreview:
    """A tailored résumé previews as its own text, with the changes marked."""

    BASE = {
        "language": "fr",
        "document_title": "CV — Stage ML",
        "blocks": [
            {"index": 0, "text": "Alex Martin", "bold": True, "alignment": "center"},
            {"index": 1, "text": ""},
            {"index": 2, "text": "Objectif : [Poste visé]"},
            {"index": 3, "text": "Pipeline de données chez Acme"},
        ],
        "slots": [
            {
                "key": "s0",
                "token": "[Poste visé]",
                "block": 2,
                "start": 11,
                "end": 23,
                "line": "Objectif : [Poste visé]",
            }
        ],
        "fills": [{"slot": "s0", "text": "Stage Machine Learning"}],
    }

    def test_it_is_recognised_as_filled_rather_than_legacy(self):
        assert render.is_filled(self.BASE)
        assert not render.is_filled(RESUME)
        assert not render.is_filled(LETTER)

    def test_the_preview_shows_the_finished_text(self):
        markup = render.render_artifact("resume", self.BASE)

        assert "Objectif : Stage Machine Learning" in markup
        assert "Pipeline de données chez Acme" in markup
        assert "[Poste visé]" not in markup.split("<del")[0]

    def test_the_changed_line_is_marked_and_the_others_are_not(self):
        markup = render.render_artifact("resume", self.BASE)
        # Only the rendered paragraphs — the stylesheet above them also names
        # the class.
        rows = markup.split("<div class='sheet'>")[1].split('<p class="')[1:]

        changed = [row for row in rows if row.startswith(("body changed", "cell changed"))]
        assert len(changed) == 1
        assert "Stage Machine Learning" in changed[0]

    def test_the_preview_says_the_download_is_the_real_document(self):
        markup = render.render_artifact("resume", self.BASE)

        assert "1 line(s) filled in" in markup
        assert "your fonts, spacing and layout" in markup

    def test_a_legacy_resume_still_renders_through_the_same_entry_point(self):
        markup = render.render_artifact("resume", RESUME)

        assert "INSA Lyon" in markup
        assert "Relevant Coursework" in markup


class TestArtifactText:
    """What the Copy button on a cover letter puts on the clipboard.

    Plain text rather than the preview's markup, because the form it is pasted
    into is a textarea. Assembled here rather than in the frontend so there is
    one answer to what the employer reads — the slicing rules in
    `docx_template.filled_lines` are subtle enough that a second implementation
    of them in TypeScript would be a second, quietly different letter.
    """

    FILLED = {
        "language": "en",
        "blocks": [
            {"index": 0, "text": "Dear [recipient],"},
            {"index": 1, "text": ""},
            {"index": 2, "text": "[address_company]"},
            {"index": 3, "text": "Your work on [subject] is why I am writing."},
        ],
        "slots": [
            {"key": "s0", "token": "[recipient]", "block": 0, "start": 5, "end": 16, "line": ""},
            {"key": "s1", "token": "[address_company]", "block": 2, "start": 0, "end": 17, "line": ""},
            {"key": "s2", "token": "[subject]", "block": 3, "start": 13, "end": 22, "line": ""},
        ],
        "fills": [
            {"slot": "s0", "text": "Nimbus Labs hiring team"},
            # The posting gave no street. An empty fill is an answer, and the
            # letter must not go out saying "[address_company]".
            {"slot": "s1", "text": ""},
            {"slot": "s2", "text": "sparse retrieval"},
        ],
    }

    def test_it_is_the_letter_with_its_blanks_filled(self):
        text = render.artifact_text("cover_letter", self.FILLED, candidate_name="Alex Martin")

        assert text.startswith("Dear Nimbus Labs hiring team,")
        assert "Your work on sparse retrieval is why I am writing." in text
        assert text.endswith("Alex Martin")
        assert "[" not in text

    def test_blank_paragraphs_survive_as_blank_lines(self):
        """The paragraph breaks are most of what a paste into a textarea keeps."""
        lines = render.artifact_text("cover_letter", self.FILLED).split("\n")

        assert lines[1] == ""
        # The unanswered address, written as the empty line it was filled with.
        assert lines[2] == ""

    def test_it_extracts_from_salutation_to_goodbye_french(self):
        content = {
            "language": "fr",
            "blocks": [
                {"index": 0, "text": "Lettre de motivation"},
                {"index": 1, "text": "Alex Martin"},
                {"index": 2, "text": "alex@example.com · Paris"},
                {"index": 3, "text": "Eaubonne, le 18 septembre 2026"},
                {"index": 4, "text": "Équipe Mistral"},
                {"index": 5, "text": "Objet : Candidature au stage ML"},
                {"index": 6, "text": "Madame, Monsieur,"},
                {"index": 7, "text": ""},
                {"index": 8, "text": "Je vous écris pour postuler au stage ML."},
                {"index": 9, "text": ""},
                {
                    "index": 10,
                    "text": (
                        "Dans cette perspective, veuillez agréer, Madame, Monsieur, "
                        "l’expression de mes salutations distinguées."
                    ),
                },
                {"index": 11, "text": ""},
            ],
            "slots": [],
            "fills": [],
        }
        text = render.artifact_text("cover_letter", content, candidate_name="Alex Martin")

        assert text.startswith("Madame, Monsieur,")
        expected_suffix = (
            "Dans cette perspective, veuillez agréer, Madame, Monsieur, "
            "l’expression de mes salutations distinguées.\n\nAlex Martin"
        )
        assert text.endswith(expected_suffix)
        assert "Lettre de motivation" not in text
        assert "Objet :" not in text
        assert "Eaubonne" not in text

    def test_a_letter_with_no_known_name_is_signed_by_nobody(self):
        # It used to fall back to a hard-coded name — the original author's —
        # so anyone else's letter, run before their profile had a name, went
        # out signed by a stranger. No name known means no name written.
        text = render.artifact_text("cover_letter", self.FILLED)

        assert text.endswith("Your work on sparse retrieval is why I am writing.")

    def test_it_extracts_from_salutation_to_goodbye_english(self):
        content = {
            "language": "en",
            "blocks": [
                {"index": 0, "text": "Cover Letter"},
                {"index": 1, "text": "Alex Martin"},
                {"index": 2, "text": "alex@example.com"},
                {"index": 3, "text": "September 18, 2026"},
                {"index": 4, "text": "Hiring Team"},
                {"index": 5, "text": "Job reference: ML Engineer"},
                {"index": 6, "text": "Dear Recruiter:"},
                {"index": 7, "text": ""},
                {"index": 8, "text": "I am writing to apply for the ML Engineer internship."},
                {"index": 9, "text": ""},
                {"index": 10, "text": "Sincerely,"},
            ],
            "slots": [],
            "fills": [],
        }
        text = render.artifact_text("cover_letter", content, candidate_name="Alex Martin")

        assert text.startswith("Dear Recruiter:")
        assert text.endswith("Sincerely,\n\nAlex Martin")
        assert "Cover Letter" not in text
        assert "Job reference:" not in text
        assert "September 18" not in text

    def test_a_legacy_letter_still_has_a_text_form(self):
        text = render.artifact_text("cover_letter", LETTER)

        assert text.startswith("Bonjour,")
        assert "Hiring team" not in text
        assert "ML internship application" not in text
        assert "Your work on sparse retrieval is why I am writing." in text
        assert text.endswith("Alex Martin")

    def test_a_legacy_resume_has_none_on_purpose(self):
        """Only the letter is ever pasted, and flattening the old résumé shape
        would be a layout decision with no reader to check it against."""
        with pytest.raises(ValueError):
            render.artifact_text("resume", RESUME)
