"""SQLite engine + session helpers.

The whole app is single-user and local, so one SQLite file with WAL enabled is
plenty. `AuditPlugin` writes from inside agent callbacks that may run
concurrently (ParallelAgent), hence WAL + a busy timeout.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from ..config import get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None


def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            f"sqlite:///{settings.db_path}",
            echo=False,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        event.listen(_engine, "connect", _configure_sqlite)
    return _engine


def _add_missing_columns() -> None:
    """Additive-only auto-migration.

    `create_all` creates missing *tables* but never alters existing ones, so
    adding a field to a model silently breaks an existing database. This is a
    single-user local app where a full migration tool would be overkill, but
    losing your interview and playbook to a schema change is not acceptable
    either — so new nullable/defaulted columns are added in place.

    Deliberately does not handle drops, renames or type changes: those are rare
    enough to be worth a conscious `make reset-db`.
    """
    from sqlalchemy import inspect, text

    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                ddl_type = column.type.compile(engine.dialect)
                default = column.default.arg if column.default is not None else None
                if callable(default):
                    default = None
                clause = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}'
                if isinstance(default, str):
                    clause += f" DEFAULT '{default}'"
                elif isinstance(default, (int, float)):
                    clause += f" DEFAULT {default}"
                logger.info("Adding column %s.%s", table.name, column.name)
                connection.execute(text(clause))


# Columns a model lost that must actually be **dropped**, not merely left unread.
#
# `_add_missing_columns` deliberately handles no drops, and normally that is
# right: an unread column costs a few bytes. The ones listed here are the
# exception, and the reason is `NOT NULL`.
#
# SQLModel maps `field: str = ""` to `VARCHAR NOT NULL` with the default applied
# in *Python*, not as a SQL `DEFAULT`. So the moment the field leaves the model,
# every INSERT omits the column — and SQLite rejects it:
#
#     IntegrityError: NOT NULL constraint failed: profile_source.canva_design_id
#
# Which means removing the Canva integration bricked every profile import and
# every saved artifact on an existing database, while passing the whole test
# suite: tests build their schema from the current models, so the column was
# never there to violate. Found on 2026-08-28 by uploading a base résumé to a
# real database rather than a fresh one.
#
# `ALTER TABLE … DROP COLUMN` has been in SQLite since 3.35 (2021).
RETIRED_COLUMNS = (
    ("profile", "canva_resume_url"),
    ("profile_source", "canva_design_id"),
    ("application_artifact", "canva_design_id"),
    ("application_artifact", "canva_edit_url"),
    # 2026-08-29: one free-text "further background" box, replaced by the two
    # curated lists the résumé's blanks are filled from (`profile.courses`,
    # `profile.skills_pool`). Same reason as the Canva columns: SQLModel maps
    # `field: str = ""` to a NOT NULL column whose default is applied in Python,
    # so a field the model no longer has is a constraint no insert can satisfy.
    ("profile", "extra_context"),
    # 2026-09-08: those two lists in turn, now that an item has to exist in both
    # languages. Their lines are copied into `candidate_list_item` rows by
    # `_seed_candidate_lists`, which runs first — see it for why the columns go
    # rather than staying as a fallback.
    ("profile", "courses"),
    ("profile", "skills_pool"),
)


def _seed_candidate_lists() -> None:
    """Carry the old one-line-per-item lists into the bilingual table.

    2026-09-08. `profile.courses` and `profile.skills_pool` were two text boxes
    the candidate typed once, in whichever language they thought in; they are
    rows now, each carrying an English *and* a French spelling, because the
    Tailor was translating them mid-run inside a blank measured in characters.

    Those boxes hold real work — sixteen course titles and forty skills on the
    live database — so they are not dropped from under it. Each non-blank line
    becomes an item **with the same text on both sides**, which is already right
    for most of the skills (`Python`, `Docker`, `MLflow` are spelled the same in
    both) and is the honest starting point for the rest: the Account page shows
    every item in both languages side by side, so a course still reading
    `Probabilités` in its English field is visible as work to do rather than a
    silent wrong answer. It is also what the old behaviour amounted to — one
    spelling used in both languages — except that it is now on the page instead
    of inside a prompt.

    Runs once: only when the table is empty, so re-running it after the
    candidate has edited an item cannot resurrect the original wording. Silent
    when there is nothing to carry, which is every boot after the first and
    every fresh install.
    """
    from sqlalchemy import inspect, text

    from .models import utcnow

    engine = get_engine()
    inspector = inspect(engine)
    if "profile" not in set(inspector.get_table_names()):
        return
    columns = {item["name"] for item in inspector.get_columns("profile")}
    legacy = [
        (column, kind)
        for column, kind in (("courses", "course"), ("skills_pool", "skill"))
        if column in columns
    ]
    if not legacy:
        return

    with engine.begin() as connection:
        already = connection.execute(
            text("SELECT COUNT(*) FROM candidate_list_item")
        ).scalar_one()
        if already:
            return
        for column, kind in legacy:
            rows = connection.execute(text(f"SELECT {column} FROM profile")).fetchall()
            lines = [
                line.strip()
                for (raw,) in rows
                for line in str(raw or "").splitlines()
                if line.strip()
            ]
            seen: set[str] = set()
            position = 0
            for line in lines:
                if line.casefold() in seen:
                    continue
                seen.add(line.casefold())
                connection.execute(
                    text(
                        "INSERT INTO candidate_list_item "
                        "(kind, en, fr, position, created_at, updated_at) "
                        "VALUES (:kind, :text, :text, :position, :now, :now)"
                    ),
                    {
                        "kind": kind,
                        "text": line,
                        "position": position,
                        "now": utcnow().replace(tzinfo=None),
                    },
                )
                position += 1
            if position:
                logger.info(
                    "Seeded %s %s(s) from profile.%s into candidate_list_item. "
                    "Both languages hold the original wording — check them on the Account page.",
                    position, kind, column,
                )


def _retire_removed_values() -> None:
    """Clear out rows holding an enum value the app no longer has.

    The complement of `_add_missing_columns`: that one handles a model gaining
    a field, this one handles a model *losing* a value. Both are needed for the
    same reason — the database outlives the schema that wrote it, and this app's
    data is the user's own job search, not something to recreate.

    The retirements, oldest first:

    * `application.status = 'screening'` → `'applied'`. The status was removed
      because it describes the employer's internal state; `applied` is the
      honest reading of a row that carried it — sent, no decision yet. The
      `application_event` rows keep saying `screening`, because those are
      history: the transition really did happen.
    * `application.status = 'interview'` → `'hr_pre_call'` (2026-10-05). The
      one interview column was split into four rounds; the first round is the
      honest reading of "they answered and we are talking", and the candidate
      moves a row further by hand. Events keep saying `interview`, as history.
    * `application_artifact.kind = 'plan'` rows are deleted. The Step agent that
      wrote them is gone, nothing renders them, and leaving them behind would
      put a "plan" badge on Tracker cards for an artifact no page can open.
    * `profile_source.kind = 'canva'` rows are deleted along with the two Canva
      tables. Dropping a table is not something `_add_missing_columns` will ever
      do, and these two are not ordinary dead weight: `canva_token` holds a live
      OAuth access and refresh token for the user's Canva account, and an
      integration that has been removed should not leave credentials for it
      sitting in the database.
    * `non_negotiables` is stripped out of `profile.data`. Pins were removed
      because the new résumé design makes them unenforceable *and* unnecessary:
      an applying run edits lines of the candidate's own document and has no way
      to drop an experience, so "this must appear" is now structural rather than
      a promise. Left in place the key would be a stale list nothing reads.
    * Every `RETIRED_COLUMNS` entry is dropped — see that constant for why this
      is the one case where leaving a removed column alone does not work. The two
      2026-09-08 additions are read by `_seed_candidate_lists` first, so their
      contents survive the drop as rows.

    Idempotent, and silent when there is nothing to do — which is the normal
    case on every boot after the first.
    """
    import json

    from sqlalchemy import inspect, text

    with get_engine().begin() as connection:
        moved = connection.execute(
            text("UPDATE application SET status = 'applied' WHERE status = 'screening'")
        ).rowcount
        if moved:
            logger.info("Moved %s application(s) from the removed 'screening' status to 'applied'", moved)
        moved = connection.execute(
            text("UPDATE application SET status = 'hr_pre_call' WHERE status = 'interview'")
        ).rowcount
        if moved:
            logger.info(
                "Moved %s application(s) from the removed 'interview' status to 'hr_pre_call'", moved
            )
        dropped = connection.execute(
            text("DELETE FROM application_artifact WHERE kind = 'plan'")
        ).rowcount
        if dropped:
            logger.info("Deleted %s obsolete application plan artifact(s)", dropped)

        canva = connection.execute(
            text("DELETE FROM profile_source WHERE kind = 'canva'")
        ).rowcount
        if canva:
            logger.info("Deleted %s Canva-imported profile source(s); the integration is gone", canva)
        for table in ("canva_token", "oauth_state"):
            connection.execute(text(f"DROP TABLE IF EXISTS {table}"))

        inspector = inspect(get_engine())
        tables = set(inspector.get_table_names())
        for table, column in RETIRED_COLUMNS:
            if table not in tables:
                continue
            if column not in {item["name"] for item in inspector.get_columns(table)}:
                continue
            try:
                connection.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{column}"'))
                logger.info("Dropped the retired column %s.%s", table, column)
            except Exception:
                # Worth a loud message rather than a silent pass: while this
                # column is still there and NOT NULL, every insert into that
                # table fails.
                logger.exception(
                    "Could not drop %s.%s. Inserts into %s will fail until it is gone — "
                    "SQLite needs 3.35+ for DROP COLUMN, or run `make reset-db`.",
                    table, column, table,
                )

        rows = connection.execute(text("SELECT id, data FROM profile")).fetchall()
        for row_id, raw in rows:
            try:
                data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except (TypeError, ValueError):
                continue
            if not isinstance(data, dict) or "non_negotiables" not in data:
                continue
            data.pop("non_negotiables")
            connection.execute(
                text("UPDATE profile SET data = :data WHERE id = :id"),
                {"data": json.dumps(data), "id": row_id},
            )
            logger.info("Removed the retired non_negotiables pins from profile %s", row_id)


def init_db() -> None:
    # Importing for the side effect of registering the tables on SQLModel.metadata.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(get_engine())
    try:
        _add_missing_columns()
    except Exception:
        logger.exception(
            "Could not add new columns to the existing database. "
            "If the app misbehaves, run `make reset-db`."
        )
    try:
        _seed_candidate_lists()
    except Exception:
        logger.exception(
            "Could not carry the old courses/skills text into the bilingual list table. "
            "The lists may need retyping on the Account page."
        )
    try:
        _retire_removed_values()
    except Exception:
        logger.exception("Could not retire removed enum values from the existing database.")
    try:
        from ..services import search_history

        search_history.backfill_from_runs()
    except Exception:
        logger.exception("Could not backfill search history from past runs.")


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session. Commits on success, rolls back on failure."""
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
