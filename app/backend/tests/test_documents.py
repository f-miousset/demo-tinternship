"""Document parsing: LinkedIn archives, DOCX, and unsupported types."""

from __future__ import annotations

import io
import zipfile

import pytest

from tinternship_backend.services.documents import (
    looks_like_linkedin_archive,
    parse_linkedin_archive,
    payload_for_upload,
)


def build_archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


SAMPLE = {
    "Profile.csv": (
        "First Name,Last Name,Headline,Summary,Geo Location,Websites\n"
        "Alex,Martin,CS student,Building things,\"Paris, France\",https://example.com\n"
    ),
    "Positions.csv": (
        "Company Name,Title,Description,Location,Started On,Finished On\n"
        "Acme,Software Intern,Built the ingest pipeline,Paris,Jun 2025,Sep 2025\n"
        "Beta Lab,Research Assistant,Ran experiments,Lyon,Jan 2026,\n"
    ),
    "Education.csv": (
        "School Name,Start Date,End Date,Notes,Degree Name,Activities\n"
        "INSA Lyon,2023,2028,,Engineering degree,Robotics club\n"
    ),
    "Skills.csv": "Name\nPython\nPyTorch\nFrench\n",
    "Languages.csv": "Name,Proficiency\nFrench,Native\nEnglish,Full professional\n",
    "Email Addresses.csv": "Email Address,Primary\nalex@example.com,Yes\n",
}


class TestLinkedInArchive:
    def test_detects_a_real_archive(self):
        assert looks_like_linkedin_archive("Basic_LinkedInDataExport.zip", build_archive(SAMPLE))

    def test_rejects_an_unrelated_zip(self):
        assert not looks_like_linkedin_archive("photos.zip", build_archive({"a.txt": "hi"}))

    def test_rejects_a_non_zip(self):
        assert not looks_like_linkedin_archive("resume.pdf", b"%PDF-1.7")

    def test_parses_every_section(self):
        profile = parse_linkedin_archive(build_archive(SAMPLE))
        assert profile.full_name == "Alex Martin"
        assert profile.headline == "CS student"
        assert profile.email == "alex@example.com"
        assert profile.location == "Paris, France"
        assert len(profile.experiences) == 2
        assert profile.experiences[0].organisation == "Acme"
        # An empty "Finished On" means the role is current.
        assert profile.experiences[1].end_date == "Present"
        assert profile.education[0].institution == "INSA Lyon"
        assert "PyTorch" in profile.skills
        assert {entry.language for entry in profile.languages} == {"French", "English"}

    def test_flags_an_archive_with_no_career_data(self):
        profile = parse_linkedin_archive(build_archive({"Profile.csv": SAMPLE["Profile.csv"]}))
        assert "full LinkedIn data export" in profile.extraction_notes

    def test_handles_nested_folder_layout(self):
        # LinkedIn sometimes nests everything under a folder.
        nested = {f"Basic_LinkedInDataExport/{name}": body for name, body in SAMPLE.items()}
        profile = parse_linkedin_archive(build_archive(nested))
        assert len(profile.experiences) == 2


class TestUploadDispatch:
    def test_pdf_is_sent_as_an_attachment_not_extracted_text(self):
        payload = payload_for_upload("resume.pdf", b"%PDF-1.7\n%not a real pdf")
        assert payload.parts, "PDFs must reach Gemini as a file part"
        assert payload.parts[0].inline_data.mime_type == "application/pdf"

    def test_plain_text_is_inlined(self):
        payload = payload_for_upload("notes.txt", b"Experience: built things")
        assert not payload.parts
        assert "built things" in payload.text

    def test_unsupported_extension_is_rejected_with_guidance(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            payload_for_upload("resume.pages", b"\x00\x01")
