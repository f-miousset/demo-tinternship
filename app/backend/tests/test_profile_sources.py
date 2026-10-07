"""Serving back the documents that were imported into the profile.

The Account page lists one row per imported document and now links to the file
itself, so the row has to say truthfully whether that file is still there, and
the endpoint has to refuse to read anything outside the uploads directory — a
`profile_source` row is stored data, not a licence to open arbitrary paths.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tinternship_backend.config import get_settings
from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import ProfileSource, ProfileSourceKind
from tinternship_backend.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def store_source(name: str, data: bytes, *, kind: str = ProfileSourceKind.UPLOAD_PDF) -> int:
    path = get_settings().uploads_path / name
    path.write_bytes(data)
    return add_source(kind=kind, label=name, file_path=str(path))


def add_source(*, kind: str, label: str, file_path: str) -> int:
    with session_scope() as session:
        source = ProfileSource(kind=kind, label=label, file_path=file_path, status="parsed")
        session.add(source)
        session.flush()
        return source.id


def test_an_uploaded_pdf_comes_back_inline(client: TestClient):
    source_id = store_source("resume.pdf", b"%PDF-1.7\n%stub\n")

    response = client.get(f"/api/profile/sources/{source_id}/file")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "inline" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_an_archive_is_offered_as_a_download(client: TestClient):
    source_id = store_source(
        "export.zip", b"PK\x03\x04stub", kind=ProfileSourceKind.LINKEDIN_ARCHIVE
    )

    response = client.get(f"/api/profile/sources/{source_id}/file")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]


def test_the_listing_says_what_can_be_shown(client: TestClient):
    store_source("resume.pdf", b"%PDF-1.7\n")
    store_source("export.zip", b"PK\x03\x04", kind=ProfileSourceKind.LINKEDIN_ARCHIVE)
    add_source(kind=ProfileSourceKind.MANUAL, label="Typed in by hand", file_path="")

    sources = {source["label"]: source for source in client.get("/api/profile").json()["sources"]}

    assert sources["resume.pdf"]["file_name"] == "resume.pdf"
    assert sources["resume.pdf"]["can_preview"] is True
    assert sources["export.zip"]["file_name"] == "export.zip"
    assert sources["export.zip"]["can_preview"] is False
    assert sources["Typed in by hand"]["file_name"] == ""


def test_a_file_deleted_off_disk_is_not_offered_or_served(client: TestClient):
    source_id = store_source("gone.pdf", b"%PDF-1.7\n")
    (get_settings().uploads_path / "gone.pdf").unlink()

    listed = client.get("/api/profile").json()["sources"][0]
    response = client.get(f"/api/profile/sources/{source_id}/file")

    assert listed["file_name"] == ""
    assert listed["can_preview"] is False
    assert response.status_code == 404


def test_a_path_outside_the_uploads_directory_is_refused(client: TestClient):
    outside = get_settings().data_path / "tinternship.db"
    outside.touch()
    source_id = add_source(
        kind=ProfileSourceKind.UPLOAD_PDF, label="../tinternship.db", file_path=str(outside)
    )

    assert client.get(f"/api/profile/sources/{source_id}/file").status_code == 404


def test_an_unknown_source_is_a_404(client: TestClient):
    assert client.get("/api/profile/sources/9999/file").status_code == 404
