"""The cover letter, since it stopped being written from scratch.

It is the same operation as the résumé — fill the blanks in the candidate's own
.docx, touch nothing else — so most of it is covered by
`test_docx_template.py` and `test_base_documents.py`. What is only true of the
letter has its tests here:

* some blanks are answered in Python before the agent is asked anything, because
  a model has no clock and the employer's name is a column;
* its address lines may come back empty, because the honest answer to "what
  street are they on" is often that nobody knows — and an invented one is a
  fabricated fact on a document going to an employer;
* every blank, Python's included, ends up in the saved artifact, which is what
  keeps the export a pure function of the artifact and the file;
* the address block is **searched for** rather than guessed or left blank, by an
  agent of its own whose notes are the writer's only source for it;
* the prose is **humanised** before the Critic sees it, by a step whose remit
  Python draws and whose rewrites Python merges.
"""

from __future__ import annotations

from datetime import date

import pytest
from conftest import (
    agents_by_name,
    applying_critics,
    applying_producers,
    build_letter_docx,
    build_letter_plan,
    build_plan,
    install_base_document,
)
from fastapi.testclient import TestClient
from sqlmodel import select

from tinternship_backend.agents.applying import (
    ADDRESS_STATE_KEY,
    COVER_LETTER_STATE_KEY,
    HUMANISER_STATE_KEY,
    MergeProse,
    build_applying_team,
    hard_check,
    merged_fills,
    prose_keys,
)
from tinternship_backend.agents.schemas import MasterProfile
from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    Application,
    ApplicationArtifact,
    ArtifactKind,
    JobPosting,
)
from tinternship_backend.main import create_app
from tinternship_backend.services import docx_template, flows, letter_fields, profile_store, render
from tinternship_backend.services.base_documents import COVER_LETTER


def _key(plan, token: str) -> str:
    return next(slot.key for slot in plan.slots if slot.token == token)


# The three paragraphs are the length a real letter's paragraphs are, and that
# is load-bearing rather than decorative. `page_fit.short_problems` refuses a
# letter that leaves most of its page empty, so a one-sentence stub is no longer
# "a set of fills that passes the gate" — it is exactly the failure the gate was
# added for on 2026-09-10. Roughly 700 characters each: under the per-blank cap
# the fixture prices at ~718, over the 1,924 the whole page asks for.
_OPENING = (
    "I am writing about the Data Scientist Intern position in your Paris office, which I "
    "found on your careers page last week. Three things make me a good fit for it. I have "
    "spent two years building data pipelines in Python and SQL, most recently one that a "
    "reporting team depended on every morning. I have shipped a model into production and "
    "watched what that costs in monitoring and retraining. And the applied, measurement-led "
    "work this posting describes is the work I have been steering my degree towards since "
    "my second year, which finishes in June. I would rather spend an internship making one "
    "pipeline genuinely dependable than touring five teams, and this posting reads as though "
    "you want the same thing."
)
_MIDDLE = (
    "At SAP I took over the pipeline behind the daily reports after it had been failing "
    "silently for a month, traced the fault to an upstream schema change nobody had "
    "announced, and rebuilt the ingestion so that a change like that fails loudly instead. "
    "It has run without intervention since. Before that I wrote the deduplication step for a "
    "customer dataset of eleven million rows, which cut manual correction work by about a "
    "day a week. Both are the kind of unglamorous data quality work your posting puts first, "
    "and both taught me more about production data than any coursework did. My database "
    "design coursework is what let me read that schema change for what it was."
)
_CLOSING = (
    "I would be glad to talk this through with you. What draws me to your team specifically "
    "is that the posting asks for someone who will own the quality of the data rather than "
    "only its analysis, and that is the half of the job I have found I am best at. I am "
    "available from March, in Paris or hybrid, and I can send the pipeline work described "
    "above as a short write-up if that would be useful. Thank you for taking the time to "
    "read this, and I look forward to hearing from you. If it is easier to start from a "
    "conversation than from a document, I am happy to do that instead, and can make myself "
    "free at short notice, including outside working hours if that suits your team better."
)


def _complete(plan, **overrides) -> dict:
    """A set of fills that passes the gate, before the overrides are applied."""
    text = {
        "[team_name]": "Data Science",
        "[address_company]": "12 rue de la Paix",
        "[city_company]": "Paris",
        "[job_posting_name]": "Data Scientist Intern",
        "[cover_letter_opening_paragraph]": _OPENING,
        "[cover_letter_middle_paragraph]": _MIDDLE,
        "[cover_letter_closing_paragraph]": _CLOSING,
        **overrides,
    }
    return {
        "fills": [
            {"slot": _key(plan, token), "text": value}
            for token, value in text.items()
            if token in [slot.token for slot in plan.slots]
        ]
    }


class TestPythonAnswersWhatItCan:
    def test_the_date_is_taken_from_the_clock(self):
        """A model has none. Asked to date a letter it writes a plausible date,
        which is the failure mode every link check exists for."""
        facts = letter_fields.LetterFacts(language="en", today=date(2026, 9, 9))
        slots = docx_template.find_slots(docx_template.read_blocks(build_letter_docx()))

        fills = letter_fields.known_fills(slots, facts)

        assert fills[_slot(slots, "[current_month_letters]")] == "September"
        assert fills[_slot(slots, "[current_date]")] == "9"

    def test_french_writes_the_month_in_french(self):
        facts = letter_fields.LetterFacts(language="fr", today=date(2026, 9, 9))
        slots = docx_template.find_slots(docx_template.read_blocks(build_letter_docx()))

        fills = letter_fields.known_fills(slots, facts)

        assert fills[_slot(slots, "[current_month_letters]")] == "septembre"

    def test_the_first_of_a_french_month_is_an_ordinal(self):
        """*le 1er septembre*, and *le 2 septembre*. It is right one day in
        twelve and wrong-looking the rest of the time, which is why it is a
        rule rather than a habit."""
        facts = letter_fields.LetterFacts(language="fr", today=date(2026, 9, 1))
        slots = docx_template.find_slots(docx_template.read_blocks(build_letter_docx()))

        assert letter_fields.known_fills(slots, facts)[_slot(slots, "[current_date]")] == "1er"

    def test_english_keeps_the_plain_number(self):
        facts = letter_fields.LetterFacts(language="en", today=date(2026, 9, 1))
        slots = docx_template.find_slots(docx_template.read_blocks(build_letter_docx()))

        assert letter_fields.known_fills(slots, facts)[_slot(slots, "[current_date]")] == "1"

    def test_a_blank_it_does_not_recognise_is_left_to_the_agent(self):
        """The candidate steers a run by naming a blank. A name this module has
        never heard of is not an error — it is the agent's."""
        plan = build_letter_plan()

        assert "[cover_letter_opening_paragraph]" in [slot.token for slot in plan.open]
        assert "[job_posting_name]" in [slot.token for slot in plan.open]

    def test_an_empty_record_leaves_the_blank_to_the_agent(self):
        """A posting pasted as text may have no company name on it. Filling the
        blank with an empty string would hide it from the one writer that could
        still do something about it."""
        plan = build_letter_plan(company="")

        assert "[company_name]" in [slot.token for slot in plan.open]

    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            ("[Company Name]", "company_name"),
            ("{{current_date}}", "current_date"),
            ("<city_company>", "city_company"),
            ("[ address_company ]", "address_company"),
        ],
    )
    def test_the_name_is_read_however_it_is_written(self, token: str, expected: str):
        assert letter_fields.field_name(token) == expected


class TestTheGate:
    def test_a_complete_set_of_fills_passes(self):
        plan = build_letter_plan()

        assert hard_check(_complete(plan), plan) == ""

    def test_a_letter_that_stops_halfway_down_the_page_is_refused(self):
        """The candidate's report on 2026-09-10, and the only letter this
        design had produced by then: three one-line paragraphs, 1,131 of 2,133
        characters used, the sign-off floating eight lines above the bottom of
        the page. Nothing refused it, because until then "one page" was only
        ever checked as a ceiling."""
        plan = build_letter_plan()
        short = _complete(
            plan,
            **{
                "[cover_letter_opening_paragraph]": "I am writing about the internship.",
                "[cover_letter_middle_paragraph]": "I built a data pipeline once.",
                "[cover_letter_closing_paragraph]": "I would be glad to talk.",
            },
        )

        problem = hard_check(short, plan)

        assert "characters this page has room for" in problem
        assert "line(s) of it empty" in problem

    def test_the_refusal_names_the_paragraphs_and_not_the_address(self):
        """An address block left empty is the one honest empty answer, so the
        one thing this must never do is name it as somewhere to write more."""
        plan = build_letter_plan()
        short = _complete(
            plan,
            **{
                "[address_company]": "",
                "[cover_letter_opening_paragraph]": "Short.",
                "[cover_letter_middle_paragraph]": "Also short.",
                "[cover_letter_closing_paragraph]": "Likewise.",
            },
        )
        address = _key(plan, "[address_company]")

        problem = hard_check(short, plan)

        assert "cover_letter_opening_paragraph" not in problem  # slot keys, not tokens
        assert f"{address} (" not in problem

    def test_the_page_and_the_target_never_argue_in_the_same_breath(self):
        """A run that spilled the page is told about the page. Being told to
        lengthen and shorten the same letter in one message is a revision round
        with no move that satisfies it."""
        plan = build_letter_plan()
        spilled = _complete(plan, **{"[cover_letter_middle_paragraph]": "mots " * 400})

        problem = hard_check(spilled, plan)

        assert "characters this page has room for" not in problem

    def test_an_empty_address_is_written_as_nothing_not_as_the_placeholder(self):
        """Falling back to the token here would print `[address_company]` on a
        document going to an employer, which is the worst thing this can do."""
        plan = build_letter_plan()
        fills = merged_fills(_complete(plan, **{"[address_company]": ""}), plan)

        lines = docx_template.filled_lines(plan.blocks, plan.slots, fills)
        address = next(slot for slot in plan.slots if slot.token == "[address_company]")

        assert lines[address.block] == ""

    def test_a_blank_nobody_answered_keeps_its_token(self):
        """The other half of the same rule: an unfilled blank stays visible, so
        the preview shows what was missed instead of a line short of a word."""
        plan = build_letter_plan()
        artifact = _complete(plan)
        artifact["fills"] = [
            entry
            for entry in artifact["fills"]
            if entry["slot"] != _key(plan, "[address_company]")
        ]

        lines = docx_template.filled_lines(
            plan.blocks, plan.slots, merged_fills(artifact, plan)
        )
        address = next(slot for slot in plan.slots if slot.token == "[address_company]")

        assert lines[address.block] == "[address_company]"

    def test_an_unknown_street_may_be_left_empty(self):
        """The one place an empty answer is the honest one. An invented address
        is a fabricated fact on a document going to an employer, and a blank
        line in an address block is what a letter with no street looks like."""
        plan = build_letter_plan()

        assert hard_check(_complete(plan, **{"[address_company]": ""}), plan) == ""

    def test_an_empty_paragraph_is_still_refused(self):
        """"Unknown" is not a thing a paragraph can be."""
        plan = build_letter_plan()

        problems = hard_check(
            _complete(plan, **{"[cover_letter_middle_paragraph]": "  "}), plan
        )

        assert "came back empty" in problems

    def test_a_missing_paragraph_is_refused(self):
        plan = build_letter_plan()

        assert "left unfilled" in hard_check({"fills": []}, plan)

    def test_a_line_break_inside_a_paragraph_is_refused(self):
        """One blank is one paragraph of the candidate's layout. Splitting it
        adds a line they did not lay out."""
        plan = build_letter_plan()

        problems = hard_check(
            _complete(plan, **{"[cover_letter_opening_paragraph]": "One.\nTwo."}), plan
        )

        assert "line break" in problems

    def test_a_letter_that_spills_the_page_is_refused(self):
        """The candidate's rule applies to both documents, and a letter is the
        one with room to break it: three paragraphs is a page of prose."""
        plan = build_letter_plan()

        problems = hard_check(
            _complete(plan, **{"[cover_letter_middle_paragraph]": "mots " * 400}), plan
        )

        assert "second page" in problems or "budget" in problems

    def test_a_gender_indicator_is_refused(self):
        plan = build_letter_plan()
        problems = hard_check(
            _complete(plan, **{"[job_posting_name]": "Data Scientist (F/H)"}), plan
        )
        assert "gender indicator" in problems

    def test_an_all_caps_word_is_refused(self):
        plan = build_letter_plan()
        problems = hard_check(
            _complete(plan, **{"[job_posting_name]": "Expert Sécurité DATA"}), plan
        )
        assert "ALL CAPS" in problems

    def test_pythons_answer_wins_over_a_stray_fill(self):
        """The agent was never shown these blanks, so a fill for one is a stray
        rather than a disagreement — and sending a revision loop back over it
        would spend a model call to change nothing."""
        plan = build_letter_plan(company="Nimbus Labs")
        company = _key(plan, "[company_name]")
        artifact = _complete(plan)
        artifact["fills"].append({"slot": company, "text": "NIMBUS LABORATORIES SAS"})

        assert merged_fills(artifact, plan)[company] == "Nimbus Labs"
        assert hard_check(artifact, plan) == ""


class TestTheSavedArtifact:
    def test_it_carries_every_blank_including_pythons(self):
        """The export re-applies the stored fills to the stored spans. Re-deriving
        the date at download time would produce a different string, of a
        different length, months later."""
        plan = build_letter_plan(company="Nimbus Labs")
        content = _complete(plan)

        flows._record_known_fills(content, plan)

        filled = {entry["slot"]: entry["text"] for entry in content["fills"]}
        assert set(filled) == {slot.key for slot in plan.slots}
        assert filled[_key(plan, "[company_name]")] == "Nimbus Labs"

    def test_a_stray_fill_for_one_of_them_is_dropped(self):
        plan = build_letter_plan(company="Nimbus Labs")
        content = _complete(plan)
        content["fills"].append(
            {"slot": _key(plan, "[company_name]"), "text": "NIMBUS LABORATORIES SAS"}
        )

        flows._record_known_fills(content, plan)

        entries = [
            entry
            for entry in content["fills"]
            if entry["slot"] == _key(plan, "[company_name]")
        ]
        assert [entry["text"] for entry in entries] == ["Nimbus Labs"]

    def test_the_fills_stay_in_document_order(self):
        plan = build_letter_plan()
        content = _complete(plan)

        flows._record_known_fills(content, plan)

        order = [slot.key for slot in plan.slots]
        written = [entry["slot"] for entry in content["fills"]]
        assert written == sorted(written, key=order.index)


class TestThePreview:
    def test_it_shows_the_letter_as_it_will_read(self):
        install_base_document(COVER_LETTER, "en")
        plan = build_letter_plan(company="Nimbus Labs")
        content = {
            **_complete(plan),
            "language": "en",
            "blocks": docx_template.blocks_payload(plan.blocks),
            "slots": docx_template.slots_payload(plan.slots),
        }
        flows._record_known_fills(content, plan)

        markup = render.render_artifact("cover_letter", content)

        assert "Data Science Team" in markup
        assert "Nimbus Labs" in markup
        assert "cover letter .docx" in markup, "it says which document this is"
        assert "[cover_letter_opening_paragraph]" not in markup.split("<del")[0]


class TestTheClipboardCopy:
    """`GET /artifacts/{id}/text` — the Copy button beside the download.

    Many application forms have no attachment field for a letter, only a
    "motivation" box, and neither the .docx nor the scaled preview iframe can be
    pasted into one. The text is assembled on this side rather than in the
    frontend so that what gets pasted is the same string the Critic and the
    language gate were shown.
    """

    def _saved_letter(self) -> int:
        """A letter artifact on a real application, as a run would leave it."""
        install_base_document(COVER_LETTER, "en")
        plan = build_letter_plan(company="Nimbus Labs")
        content = {
            **_complete(plan),
            "language": "en",
            "blocks": docx_template.blocks_payload(plan.blocks),
            "slots": docx_template.slots_payload(plan.slots),
        }
        flows._record_known_fills(content, plan)

        with session_scope() as session:
            job = JobPosting(dedupe_key="k", title="ML Intern", company="Nimbus Labs")
            session.add(job)
            session.flush()
            application = Application(job_posting_id=job.id)
            session.add(application)
            session.flush()
            artifact = ApplicationArtifact(
                application_id=application.id,
                kind=ArtifactKind.COVER_LETTER,
                version=1,
                content=content,
            )
            session.add(artifact)
            session.flush()
            return int(artifact.id)

    def test_it_hands_back_the_letter_with_its_blanks_filled(self):
        client = TestClient(create_app())

        profile_store.save_profile(MasterProfile(full_name="Alex Martin"))
        response = client.get(f"/api/applications/artifacts/{self._saved_letter()}/text")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert response.text.startswith("Dear Recruiter:")
        assert response.text.endswith("Sincerely,\n\nAlex Martin")
        assert "alex@example.com" not in response.text
        assert "Job reference:" not in response.text
        # Accents survive the round trip, which is the whole point of the
        # charset: half of these letters are French.
        assert "utf-8" in response.headers["content-type"]
        assert "[cover_letter_opening_paragraph]" not in response.text

    def test_it_is_the_text_and_not_the_preview(self):
        client = TestClient(create_app())

        response = client.get(f"/api/applications/artifacts/{self._saved_letter()}/text")

        assert "<p" not in response.text
        assert "the download is" not in response.text, "no note to the candidate in it"

    def test_an_artifact_that_does_not_exist_is_a_404(self):
        client = TestClient(create_app())

        assert client.get("/api/applications/artifacts/9999/text").status_code == 404


def _slot(slots, token: str) -> str:
    return next(slot.key for slot in slots if slot.token == token)


class TestTheAddressIsResearched:
    """The address block is looked up, not guessed and not left blank.

    A posting almost never gives the employer's address and nothing else in this
    system knows it, so the choice was *leave the line empty* or *go and look*.
    Looking wins as long as what comes back is a page anyone can open — which is
    why the scout is a separate agent whose notes travel to the writer and to
    the Critic.
    """

    @staticmethod
    def _team():
        return build_applying_team(
            job_id=0,
            resume_plan=build_plan("en"),
            letter_plan=build_letter_plan("en"),
        )

    NOTES = (
        "Nimbus Labs SAS — 12 rue de la Paix, 75002 Paris, France (headquarters).\n"
        "Source: https://nimbus.example/mentions-legales — their own legal notice."
    )

    class Ctx:
        state: dict = {}

    def test_the_scout_runs_before_the_writer_on_the_letters_lane(self):
        """A sequence, not a second parallel branch: the writer cannot search
        for itself, so it has to start after the search is done."""
        names = agents_by_name(self._team())

        assert "address_scout" in names
        lane = names["cover_letter_track"]
        assert [child.name for child in lane.sub_agents][0] == "address_scout"

    def test_the_scout_carries_google_search_and_no_output_schema(self):
        """The two facts that make it a separate agent at all: ADK will not let
        one agent hold a search tool and an output schema."""
        scout = agents_by_name(self._team())["address_scout"]

        assert scout.tools, "the scout has nothing to search with"
        assert getattr(scout, "output_schema", None) is None

    @pytest.mark.asyncio
    async def test_the_writer_is_given_the_notes(self):
        ctx = self.Ctx()
        ctx.state = {ADDRESS_STATE_KEY: self.NOTES}

        instruction = await applying_producers(self._team())["cover_letter_agent"].instruction(ctx)

        assert "12 rue de la Paix" in instruction
        assert "the only" in instruction, "it must say the notes are the only source"

    @pytest.mark.asyncio
    async def test_the_critic_is_given_them_too(self):
        """`truthfulness` on an address is the question "was this on a page
        somebody read", which cannot be answered without the notes."""
        ctx = self.Ctx()
        ctx.state = {ADDRESS_STATE_KEY: self.NOTES}

        instruction = await applying_critics(self._team())["cover_letter_agent"].instruction(ctx)

        assert "12 rue de la Paix" in instruction

    @pytest.mark.asyncio
    async def test_a_scout_that_found_nothing_says_so_rather_than_going_quiet(self):
        """An empty block would read as "no instruction about the address" and
        an invented street is exactly what that produces."""
        instruction = await applying_producers(self._team())["cover_letter_agent"].instruction(
            self.Ctx()
        )

        assert "leave the address blanks empty" in instruction

    def test_the_search_is_its_own_stage_on_the_letters_lane(self):
        """It is the slowest thing on that lane and the one whose result the
        candidate may want to check, so the page says it is happening."""
        assert flows._applying_stage("address_scout", {}) == (
            ArtifactKind.COVER_LETTER,
            "researching",
        )
        assert "address" in flows._stage_message(ArtifactKind.COVER_LETTER, "researching", "")

    def test_the_writer_after_it_is_still_a_first_draft(self):
        """`revising` is what the gate sending an artifact back looks like.
        Following the scout is not that."""
        stages = {ArtifactKind.COVER_LETTER: "researching"}

        assert flows._applying_stage("cover_letter_agent", stages) == (
            ArtifactKind.COVER_LETTER,
            "writing",
        )


class TestTheProseIsHumanised:
    """A letter can be true, specific and well-evidenced and still be binned on
    sight for reading like a machine wrote it. That is a different failure from
    the ones the Critic scores, so it gets a step of its own — and the step is
    fenced in by Python at both ends: what it may rewrite, and what of its
    answer is kept.
    """

    @staticmethod
    def _team():
        return build_applying_team(
            job_id=0,
            resume_plan=build_plan("en"),
            letter_plan=build_letter_plan("en"),
        )

    PARAGRAPH = (
        "I am writing to express my strong interest in this position, which is a "
        "testament to my enduring passion for data engineering and its evolving "
        "landscape."
    )

    def test_it_runs_between_the_writer_and_the_critic(self):
        """Inside the loop, not after it: what it produces is what ships, so it
        is what the Critic scores and what the gate measures."""
        loop = agents_by_name(self._team())["cover_letter_agent_reviewed"]

        assert [child.name for child in loop.sub_agents] == [
            "cover_letter_agent",
            "cover_letter_humaniser",
            "cover_letter_merge",
            "cover_letter_agent_critic",
            "cover_letter_agent_gate",
        ]

    def test_it_can_only_ever_return_prose(self):
        """The whole guarantee in one line: its schema has no field for the
        employer, the date, the reference line or the address, so it cannot
        touch them however it is prompted."""
        humaniser = agents_by_name(self._team())["cover_letter_humaniser"]

        assert set(humaniser.output_schema.model_fields) == {"rewrites", "left_alone"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("language", "present", "absent"),
        [("en", "landscape", "notamment"), ("fr", "notamment", "landscape")],
    )
    async def test_the_tells_are_the_letters_own_language(self, language, present, absent):
        team = build_applying_team(
            job_id=0,
            resume_plan=build_plan(language),
            letter_plan=build_letter_plan(language),
        )

        class Ctx:
            state: dict = {}

        instruction = await agents_by_name(team)["cover_letter_humaniser"].instruction(Ctx())

        assert present in instruction
        assert absent not in instruction

    def test_python_decides_what_counts_as_prose(self):
        """Drawn on the writer's own output rather than on a list of blank
        names: a field is a field whatever the candidate called it, and a
        paragraph named `[para2]` still gets humanised."""
        plan = build_letter_plan()
        fills = {
            _key(plan, "[team_name]"): "Data Science",
            _key(plan, "[city_company]"): "Paris",
            _key(plan, "[job_posting_name]"): "Data Scientist (H/F)",
            _key(plan, "[cover_letter_opening_paragraph]"): self.PARAGRAPH,
        }

        assert prose_keys(fills, plan) == [_key(plan, "[cover_letter_opening_paragraph]")]

    def test_a_blank_the_record_answered_is_never_prose(self):
        plan = build_letter_plan(company=" ".join(["Nimbus"] * 20))

        assert not set(prose_keys({key: text for key, text in plan.auto.items()}, plan))

    @pytest.mark.asyncio
    async def test_the_merge_applies_a_rewrite_in_place(self):
        plan = build_letter_plan()
        opening = _key(plan, "[cover_letter_opening_paragraph]")
        artifact = _complete(plan, **{"[cover_letter_opening_paragraph]": self.PARAGRAPH})
        state = {
            COVER_LETTER_STATE_KEY: artifact,
            HUMANISER_STATE_KEY: {
                "rewrites": [{"slot": opening, "text": "I am applying for the data role."}]
            },
        }

        merged = await _run_merge(plan, state)

        assert docx_template.fill_map(merged)[opening] == "I am applying for the data role."
        assert merged["humanised"] == [opening]

    @pytest.mark.asyncio
    async def test_it_cannot_reach_outside_the_prose(self):
        """The guarantee the separate schema buys: asked to rewrite the
        reference line or the employer's name, nothing happens."""
        plan = build_letter_plan(company="Nimbus Labs")
        artifact = _complete(plan, **{"[cover_letter_opening_paragraph]": self.PARAGRAPH})
        state = {
            COVER_LETTER_STATE_KEY: artifact,
            HUMANISER_STATE_KEY: {
                "rewrites": [
                    {"slot": _key(plan, "[job_posting_name]"), "text": "Data Scientist"},
                    {"slot": _key(plan, "[company_name]"), "text": "NIMBUS LABORATORIES"},
                ]
            },
        }

        merged = await _run_merge(plan, state)

        fills = merged_fills(merged, plan)
        assert fills[_key(plan, "[job_posting_name]")] == "Data Scientist Intern"
        assert fills[_key(plan, "[company_name]")] == "Nimbus Labs"

    @pytest.mark.asyncio
    async def test_leaving_the_prose_alone_is_a_valid_answer(self):
        """An agent that must produce something for every input produces churn."""
        plan = build_letter_plan()
        state = {
            COVER_LETTER_STATE_KEY: _complete(plan),
            HUMANISER_STATE_KEY: {"rewrites": [], "left_alone": ["s8: already reads well"]},
        }

        merged = await _run_merge(plan, state)

        assert "humanised" not in merged

    @pytest.mark.asyncio
    async def test_a_rewrite_over_budget_is_still_refused_by_the_gate(self):
        """It runs before the Critic and the gate on purpose: whatever it does
        to the letter has to survive the same arithmetic the writer's fills do."""
        plan = build_letter_plan()
        opening = _key(plan, "[cover_letter_opening_paragraph]")
        state = {
            COVER_LETTER_STATE_KEY: _complete(
                plan, **{"[cover_letter_opening_paragraph]": self.PARAGRAPH}
            ),
            HUMANISER_STATE_KEY: {"rewrites": [{"slot": opening, "text": "mots " * 400}]},
        }

        merged = await _run_merge(plan, state)

        assert "budget" in hard_check(merged, plan) or "second page" in hard_check(merged, plan)

    def test_the_rewrite_is_its_own_stage_on_the_page(self):
        assert flows._applying_stage("cover_letter_humaniser", {}) == (
            ArtifactKind.COVER_LETTER,
            "humanising",
        )


async def _run_merge(plan, state: dict) -> dict:
    """Run `MergeProse` over a state dict and return the letter it left behind.

    The merge is an ADK agent because a state change has to travel as an event
    delta — see `agents/critic.py::QualityGate`. Here the delta is applied by
    hand, which is what the runner does.
    """

    class Session:
        def __init__(self, values: dict) -> None:
            self.state = values

    class Ctx:
        invocation_id = "test"
        branch = ""

        def __init__(self, values: dict) -> None:
            self.session = Session(values)

    ctx = Ctx(state)
    async for event in MergeProse(name="merge", plan=plan)._run_async_impl(ctx):
        delta = getattr(getattr(event, "actions", None), "state_delta", None) or {}
        state.update(delta)
    return state[COVER_LETTER_STATE_KEY]


class TestTheLetterIsOptional:
    """Since 2026-09-18 a run writes the résumé; the letter is a box you tick.

    The résumé is the application — it is attached to every form — while the
    letter is wanted rarely and costs the expensive half of the run: a grounded
    search for the employer's address, a writer, a humanising pass and a Critic
    loop. So the default is off, for the button and for the run a pasted posting
    starts by itself, and the box in the Generate dialog is what turns it on.

    And it runs **alone**: *Add a cover letter* on an application that already
    has a résumé asks for the letter only, because re-writing a document that is
    already on the row is a second run producing the same file.
    """

    @staticmethod
    def _application() -> int:
        with session_scope() as session:
            job = JobPosting(dedupe_key="k", title="ML Intern", company="Nimbus Labs")
            session.add(job)
            session.flush()
            application = Application(job_posting_id=job.id)
            session.add(application)
            session.flush()
            return int(application.id)

    def test_the_team_is_one_lane_when_no_letter_was_asked_for(self):
        names = agents_by_name(build_applying_team(job_id=0, resume_plan=build_plan("en")))

        assert "resume_agent" in names
        assert "cover_letter_track" not in names
        assert "address_scout" not in names, "the grounded search is the expensive part"

    def test_ticking_the_box_brings_the_whole_lane_back(self):
        names = agents_by_name(
            build_applying_team(
                job_id=0, resume_plan=build_plan("en"), letter_plan=build_letter_plan("en")
            )
        )

        assert {"cover_letter_agent", "address_scout", "cover_letter_humaniser"} <= set(names)

    async def test_a_resume_only_run_saves_no_letter(self, monkeypatch):
        """The ADK session is keyed by posting, so a second run sees the first
        run's state. Reading the letter's key here would save the *previous*
        letter again as a new version of a document nobody asked for.
        """
        install_base_document("resume", "en")
        application_id = self._application()

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield (
                "state",
                {
                    flows.RESUME_STATE_KEY: {"fills": []},
                    # Left behind by an earlier run that did write one.
                    COVER_LETTER_STATE_KEY: {"fills": [], "full_name": "stale"},
                },
            )
            yield ("done", {"invocation_id": "inv-1"})

        monkeypatch.setattr(flows, "stream", fake_stream)

        result = await flows.run_applying(application_id, 1, "en")

        assert set(result["artifacts"]) == {ArtifactKind.RESUME}
        with session_scope() as session:
            kinds = [
                artifact.kind
                for artifact in session.exec(
                    select(ApplicationArtifact).where(
                        ApplicationArtifact.application_id == application_id
                    )
                ).all()
            ]
        assert kinds == [ArtifactKind.RESUME]

    def test_the_endpoint_defaults_the_box_to_off(self, monkeypatch):
        seen: dict = {}

        async def fake(application_id, job_id, language, personalisation="", cover_letter=False, resume=True):
            seen["cover_letter"] = cover_letter
            yield ("result", {"artifacts": {}, "run_id": 0})

        monkeypatch.setattr(flows, "applying_stream", fake)
        install_base_document("resume", "en")
        client = TestClient(create_app())

        client.post(f"/api/applications/{self._application()}/generate")

        assert seen["cover_letter"] is False

    def test_the_endpoint_passes_a_ticked_box_through(self, monkeypatch):
        seen: dict = {}

        async def fake(application_id, job_id, language, personalisation="", cover_letter=False, resume=True):
            seen["cover_letter"] = cover_letter
            yield ("result", {"artifacts": {}, "run_id": 0})

        monkeypatch.setattr(flows, "applying_stream", fake)
        install_base_document("resume", "en")
        install_base_document(COVER_LETTER, "en")
        client = TestClient(create_app())

        client.post(
            f"/api/applications/{self._application()}/generate", json={"cover_letter": True}
        )

        assert seen["cover_letter"] is True

    def test_the_team_is_the_letters_lane_alone_when_only_it_was_asked_for(self):
        names = agents_by_name(
            build_applying_team(job_id=0, letter_plan=build_letter_plan("en"))
        )

        assert {"cover_letter_agent", "address_scout"} <= set(names)
        assert "resume_agent" not in names

    def test_a_team_with_no_documents_is_a_programming_error(self):
        """A stream that produces nothing is a bug, not a request."""
        with pytest.raises(ValueError, match="at least one document"):
            build_applying_team(job_id=0)

    async def test_a_letter_only_run_saves_no_resume(self, monkeypatch):
        """The mirror of the stale-letter case, and the same mechanism: the
        session still holds the résumé this application was generated with."""
        install_base_document(COVER_LETTER, "en")
        application_id = self._application()

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield (
                "state",
                {
                    flows.RESUME_STATE_KEY: {"fills": [], "full_name": "stale"},
                    COVER_LETTER_STATE_KEY: {"fills": []},
                },
            )
            yield ("done", {"invocation_id": "inv-2"})

        monkeypatch.setattr(flows, "stream", fake_stream)

        result = await flows.run_applying(application_id, 1, "en", cover_letter=True, resume=False)

        assert set(result["artifacts"]) == {ArtifactKind.COVER_LETTER}

    async def test_asking_for_neither_is_refused_rather_than_streamed(self):
        with pytest.raises(ValueError, match="at least one document"):
            await flows.run_applying(1, 1, "en", cover_letter=False, resume=False)

    def test_the_endpoint_runs_the_letter_alone(self, monkeypatch):
        """*Add a cover letter*: the résumé on the row is left as it is."""
        seen: dict = {}

        async def fake(
            application_id, job_id, language, personalisation="", cover_letter=False, resume=True
        ):
            seen.update(cover_letter=cover_letter, resume=resume)
            yield ("result", {"artifacts": {}, "run_id": 0})

        monkeypatch.setattr(flows, "applying_stream", fake)
        install_base_document(COVER_LETTER, "en")
        client = TestClient(create_app())

        response = client.post(
            f"/api/applications/{self._application()}/generate",
            json={"cover_letter": True, "resume": False},
        )

        assert response.status_code == 200
        assert seen == {"cover_letter": True, "resume": False}

    def test_a_letter_only_run_does_not_need_a_base_resume(self, monkeypatch):
        """Only the documents this run produces are checked. The base résumé is
        installed by no fixture here, and the run still opens."""

        async def fake(
            application_id, job_id, language, personalisation="", cover_letter=False, resume=True
        ):
            yield ("result", {"artifacts": {}, "run_id": 0})

        monkeypatch.setattr(flows, "applying_stream", fake)
        install_base_document(COVER_LETTER, "en")
        client = TestClient(create_app())

        response = client.post(
            f"/api/applications/{self._application()}/generate",
            json={"cover_letter": True, "resume": False},
        )

        assert response.status_code == 200

    def test_asking_for_neither_is_a_400(self):
        client = TestClient(create_app())

        response = client.post(
            f"/api/applications/{self._application()}/generate",
            json={"cover_letter": False, "resume": False},
        )

        assert response.status_code == 400
        assert "at least one document" in response.json()["detail"]
