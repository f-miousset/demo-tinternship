"""Profile intake: the four base documents, supporting imports, and the master profile.

Two different things live behind this router and it is worth keeping them
straight. The **base documents** (`/base-document/{kind}/{language}`) are what an
employer actually receives — the candidate's own Word CV and their own Word
cover letter, one of each per language, filled in place by an applying run.
Everything else is **evidence**: files whose facts are extracted and merged into
the master profile, which is what the letter, the matcher and the interview
brief reason from. Uploading a base résumé does both, so the candidate uploads
one file rather than the same file twice; a base cover letter is only ever the
document, because a letter template holds no facts the CV has not already given.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError
from sqlmodel import select

from ..agents.schemas import MasterProfile
from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import Profile, ProfileSource, ProfileSourceKind, utcnow
from ..services import base_documents, candidate_lists, flows
from ..services.base_documents import BaseDocumentError
from ..services.languages import SUPPORTED_LANGUAGES
from ..services.profile_store import get_profile, profile_as_dict, save_profile

router = APIRouter(prefix="/api/profile", tags=["profile"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# What a browser renders in a tab. Anything else — a LinkedIn data-export ZIP —
# is offered as a download instead of being previewed.
PREVIEWABLE_SUFFIXES = {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"}


def _stored_file(source: ProfileSource) -> Path | None:
    """The imported document as it landed on disk, if it is still there.

    The path comes from one of our own rows, but it is still checked against the
    uploads directory before anything is read: a row is data, and serving
    whatever path it happens to name would turn this into a file-read primitive.
    """
    if not source.file_path:
        return None
    path = Path(source.file_path).resolve()
    if not path.is_relative_to(get_settings().uploads_path.resolve()) or not path.is_file():
        return None
    return path


def _source_payload(source: ProfileSource) -> dict[str, Any]:
    stored = _stored_file(source)
    return {
        "id": source.id,
        "kind": source.kind,
        "label": source.label,
        "status": source.status,
        "error": source.error,
        "source_url": source.source_url,
        # Empty when the document is gone from disk, so the UI offers no link to
        # a file it cannot serve.
        "file_name": stored.name if stored else "",
        "can_preview": bool(stored) and stored.suffix.lower() in PREVIEWABLE_SUFFIXES,
        "created_at": source.created_at.isoformat(),
    }


@router.get("")
def read_profile():
    profile = get_profile()
    with session_scope() as session:
        # Base documents are deliberately not in this list: they have their own
        # section, and showing them as "one of the imported sources you can
        # remove" would invite deleting the document the app cannot run without.
        sources = session.exec(
            select(ProfileSource)
            .where(
                ProfileSource.kind.notin_(  # type: ignore[attr-defined]
                    [ProfileSourceKind.BASE_RESUME, ProfileSourceKind.BASE_COVER_LETTER]
                )
            )
            .order_by(ProfileSource.created_at.desc())
        ).all()
        serialised = [_source_payload(source) for source in sources]
    return {
        "profile": profile_as_dict(),
        "has_profile": bool(profile and profile.full_name),
        "sources": serialised,
        # The documents that actually get sent, kept apart from the sources
        # list: they are not evidence that was merged in, they are the résumé
        # and the letter.
        "base_resumes": base_documents.status(base_documents.RESUME),
        "base_cover_letters": base_documents.status(base_documents.COVER_LETTER),
    }


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Résumé PDF/DOCX, LinkedIn 'Save to PDF', or a LinkedIn data-export ZIP."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 25 MB.")
    try:
        return await flows.ingest_upload(file.filename or "upload", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _base_document_kind(kind: str) -> str:
    """One of the two kinds, or a 400 naming both. Path segments are user input."""
    if kind not in base_documents.KINDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown document kind {kind!r}. Expected one of "
                f"{', '.join(base_documents.KINDS)}."
            ),
        )
    return kind


def _base_document_language(language: str) -> str:
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language {language!r}. Expected one of {', '.join(SUPPORTED_LANGUAGES)}.",
        )
    return language


@router.post("/base-document/{kind}/{language}")
async def upload_base_document(kind: str, language: str, file: UploadFile = File(...)):
    """The candidate's own Word CV or cover letter for one language — what gets sent.

    `.docx` only, and the 400 says why rather than "unsupported file type": the
    whole design is filling this file in place, and a PDF cannot be edited in
    place without becoming a different document.
    """
    kind = _base_document_kind(kind)
    language = _base_document_language(language)
    noun = base_documents.kind_of(kind).noun
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 25 MB.")
    if not base_documents.is_base_document(file.filename or ""):
        raise HTTPException(
            status_code=400,
            detail=(
                f"The base {noun} has to be a Word .docx file — its blanks are filled in "
                "place, so the document you upload is the document that gets sent. Open it in "
                "Word or LibreOffice and save it as .docx."
            ),
        )
    try:
        return await flows.ingest_base_document(
            kind, language, file.filename or f"{kind}.docx", data
        )
    except BaseDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/base-document/{kind}/{language}")
async def delete_base_document(kind: str, language: str):
    """Remove one base document. The app cannot apply in that language until it is back."""
    kind = _base_document_kind(kind)
    language = _base_document_language(language)
    noun = base_documents.kind_of(kind).noun
    source = base_documents.get(kind, language)
    if source is None:
        raise HTTPException(status_code=404, detail=f"No {language} base {noun} to remove.")
    path = base_documents.resolved_path(source)
    with session_scope() as session:
        row = session.get(ProfileSource, source.id)
        if row is not None:
            session.delete(row)
    if path is not None:
        path.unlink(missing_ok=True)
    # Only the résumé ever contributed facts, so only its removal changes the
    # profile — but re-merging either way keeps this one code path.
    profile = await flows.remerge_profile()
    return {"status": "ok", "kind": kind, "language": language, "profile": profile}


class ProfileLinks(BaseModel):
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    full_name: str | None = None
    headline: str | None = None


@router.patch("")
def update_links(body: ProfileLinks) -> dict[str, Any]:
    """Fill in the contact details, links and background that documents omit."""
    with session_scope() as session:
        profile = session.exec(select(Profile).order_by(Profile.id)).first() or Profile()
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(profile, field, value)
        profile.updated_at = utcnow()
        session.add(profile)
        session.flush()
    return {"profile": profile_as_dict()}


# ---------------------------------------------------------------------------
# The two lists the résumé's blanks are filled from
# ---------------------------------------------------------------------------


class ListItemBody(BaseModel):
    """One course or one skill, in both languages.

    Both sides are required and the service says so with the reason, because
    this is the whole point of the table: a run selects from the list *in its
    own language* and copies what it finds, so an item missing a side would have
    to be translated mid-run — which is what this replaced. See
    `services/candidate_lists.py`.
    """

    en: str = ""
    fr: str = ""


class NewListItem(ListItemBody):
    kind: str


def _lists() -> dict[str, Any]:
    return {"lists": candidate_lists.all_items()}


@router.get("/lists")
def read_lists() -> dict[str, Any]:
    """Every course and every skill, in both languages, in the candidate's order."""
    return _lists()


@router.post("/lists")
def add_list_item(body: NewListItem) -> dict[str, Any]:
    """Add one item.

    They stopped riding `PATCH /api/profile` on 2026-09-08. As two text boxes
    they were the same kind of thing as the contact details — fields the
    candidate types by hand that no extractor produces — but an item is a row
    now, and "add this course" and "I fixed a typo in that one" are different
    requests that a whole-list replace cannot tell apart.
    """
    try:
        item = candidate_lists.add(body.kind, body.en, body.fr)
    except candidate_lists.CandidateListError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**_lists(), "item": item}


@router.patch("/lists/{item_id}")
def edit_list_item(item_id: int, body: ListItemBody) -> dict[str, Any]:
    """Correct one item — mostly, fill in the language it was seeded without."""
    try:
        item = candidate_lists.update(item_id, body.en, body.fr)
    except candidate_lists.CandidateListError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**_lists(), "item": item}


@router.delete("/lists/{item_id}")
def remove_list_item(item_id: int) -> dict[str, Any]:
    try:
        candidate_lists.remove(item_id)
    except candidate_lists.CandidateListError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _lists()


class MasterProfileUpdate(BaseModel):
    """The whole profile, as edited in the Profile section of the Account page.

    A full replace rather than a patch: the editor owns every field, and a
    partial update cannot express "I deleted the third bullet".
    """

    profile: dict[str, Any]


@router.put("/master")
def replace_master(body: MasterProfileUpdate) -> dict[str, Any]:
    """Save hand-edited profile facts."""
    try:
        master = MasterProfile.model_validate(body.profile)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors(include_url=False)[:5]) from exc

    saved = save_profile(master)
    return {"profile": profile_as_dict(), "updated_at": saved.updated_at.isoformat()}


@router.get("/sources/{source_id}/file")
def read_source_file(source_id: int):
    """The imported document itself, so you can see what the extractor read."""
    with session_scope() as session:
        source = session.get(ProfileSource, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail=f"No profile source {source_id}")
        path = _stored_file(source)
    if path is None:
        raise HTTPException(status_code=404, detail="That document is no longer on disk.")
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        filename=path.name,
        content_disposition_type=(
            "inline" if path.suffix.lower() in PREVIEWABLE_SUFFIXES else "attachment"
        ),
    )


@router.delete("/sources/{source_id}")
async def delete_source(source_id: int):
    """Remove one imported document and rebuild the master profile without it."""
    with session_scope() as session:
        source = session.get(ProfileSource, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail=f"No profile source {source_id}")
        session.delete(source)
    profile = await flows.remerge_profile()
    return {"status": "ok", "profile": profile}
