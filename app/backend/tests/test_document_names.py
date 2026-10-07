"""The filename a recruiter actually sees.

Exports used to be called `resume-app12-v3.pdf`. Many ATS show the screener the
attachment's filename before they show them anything else and several file it
under that name, so the candidate's own document arrived anonymous in a folder
of hundreds — and the candidate could not find it again on their own disk
either. It is now `Resume_Alex_Martin_Acme_Data_Intern.pdf`.

Two things have to hold. The name has to survive real inputs — accents, an
employer with punctuation in it, a French posting's `(H/F)` suffix, a title
long enough to blow the budget — and the on-disk copy has to stay unique per
version, because `rendered_path` on an older artifact still points at it.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    Application,
    ApplicationArtifact,
    ArtifactKind,
    JobPosting,
    Profile,
)
from tinternship_backend.services import flows, render


class TestDocumentStem:
    def test_it_names_the_document_the_person_and_the_job(self):
        assert (
            render.document_stem(
                "resume",
                candidate="Alex Martin",
                company="Google",
                title="Software Engineering Intern",
            )
            == "Resume_Alex_Martin_Google_Software_Engineering_Intern"
        )

    def test_the_kind_is_named_in_the_package_language(self):
        """A French package arrives as a `CV`, because that is what it is."""
        stem = render.document_stem(
            "resume", candidate="Alex Martin", company="Ubisoft", title="Stage", language="fr"
        )
        assert stem.startswith("CV_Alex_Martin")

        letter = render.document_stem(
            "cover_letter",
            candidate="Alex Martin",
            company="Ubisoft",
            title="Stage",
            language="fr",
        )
        assert letter.startswith("Lettre_de_Motivation_")

    def test_punctuation_goes_and_accents_stay(self):
        """`isalnum()` is Unicode-aware. "Müller" is a name, "(H/F)" is not."""
        stem = render.document_stem(
            "resume",
            candidate="Chloé Müller",
            company="Saint-Gobain",
            title="Stage Développeur (H/F)",
        )
        assert "Chloé_Müller" in stem
        assert "Saint_Gobain" in stem
        assert "(" not in stem and "/" not in stem
        assert "H_F" not in stem and "F_H" not in stem

    def test_a_missing_part_is_dropped_rather_than_leaving_a_gap(self):
        """A posting with no company still has to export."""
        stem = render.document_stem("resume", candidate="Alex Martin", company="", title="")
        assert stem == "Resume_Alex_Martin"
        assert "__" not in stem

    @pytest.mark.parametrize(
        ("company", "title"),
        [
            ("Commissariat a l Energie Atomique et aux Energies Alternatives", "x"),
            ("Acme", "Stage de fin d etudes en apprentissage machine distribue a grande echelle"),
            (
                "Commissariat a l Energie Atomique et aux Energies Alternatives",
                "Stage de fin d etudes en apprentissage machine distribue a grande echelle",
            ),
        ],
    )
    def test_the_budget_holds_and_the_name_is_never_what_gives(self, company, title):
        """`export_artifact` cuts at 80 and `_v<n>` is appended after this, so a
        stem that overran would take the version number with it — and two
        versions would then overwrite each other on disk."""
        stem = render.document_stem(
            "cover_letter", candidate="Jean Baptiste Rousseau", company=company, title=title
        )
        assert len(stem) <= render.MAX_STEM
        assert "Jean_Baptiste_Rousseau" in stem


class TestArtifactDocumentName:
    @staticmethod
    def _seed(kind: str = ArtifactKind.RESUME, language: str = "en") -> int:
        with session_scope() as session:
            session.add(Profile(full_name="Alex Martin"))
            job = JobPosting(
                dedupe_key="acme-data-intern",
                title="Data Science Intern",
                company="Acme Labs",
            )
            session.add(job)
            session.flush()
            application = Application(job_posting_id=job.id, language=language)
            session.add(application)
            session.flush()
            artifact = ApplicationArtifact(
                application_id=application.id,
                kind=kind,
                version=3,
                content={"full_name": "Alex Martin", "language": language},
            )
            session.add(artifact)
            session.flush()
            return artifact.id

    def test_it_joins_the_profile_the_posting_and_the_kind(self):
        name = flows.artifact_document_name(self._seed())
        assert name == "Resume_Alex_Martin_Acme_Labs_Data_Science_Intern"

    def test_it_follows_the_documents_own_language_not_the_apps(self):
        name = flows.artifact_document_name(self._seed(language="fr"))
        assert name.startswith("CV_Alex_Martin")

    def test_it_falls_back_to_the_name_on_the_document_itself(self):
        """A profile can be reset while an artifact written from it survives."""
        artifact_id = self._seed()
        with session_scope() as session:
            for profile in session.exec(select(Profile)).all():
                session.delete(profile)

        assert "Alex_Martin" in flows.artifact_document_name(artifact_id)

    def test_an_unknown_artifact_raises_rather_than_naming_a_file_after_nothing(self):
        with pytest.raises(ValueError):
            flows.artifact_document_name(999999)
