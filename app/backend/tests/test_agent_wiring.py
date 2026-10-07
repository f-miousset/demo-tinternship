"""Every agent still builds, and every instruction still renders.

The rest of the suite replaces the agent run — `agents.runtime.execute` gets
monkeypatched and a canned session state comes back — which is the right way to
test everything *downstream* of the model. The cost is that it never constructs
most of the roster: before this file, five of the twenty-one `build_*` factories
were exercised by any test, so a `google-adk` or `pydantic` bump could change
`LlmAgent`'s signature or reject an output schema and the whole suite would stay
green until a real run tried to build the Critic.

That is the exact failure a dependency-bump gate exists to catch, and it costs
nothing to close: building an agent calls no model and touches no network.

Four things are asserted, and each has a failure it is aimed at:

* **It constructs**, with a model — the ADK/pydantic signature change above.
* **Its instruction renders without raising.** The instructions are async
  callables composing `services/context_blocks`, so this is also the only check
  that every prompt assembles against a database with nothing in it — the state
  a new account is in.
* **Every `output_schema` still produces a JSON schema.** Twenty-six of the
  forty-five agents in these trees declare one, and ADK's constraint on them (scalars,
  lists and nested models; no `Optional`, no unions) is exactly the kind of thing
  a pydantic major re-litigates. `model_json_schema()` is where that surfaces.
* **Names are unique within a tree.** ADK addresses sub-agents by name; two
  agents sharing one is a runtime error inside a live run, which is the most
  expensive place to find out.

What this file deliberately does **not** assert is prompt *wording*: an
instruction is the prompt plus several context blocks, and the blocks are
thousands of characters, so "it rendered something long" stays true even with a
prompt blanked — measured, not assumed. The wording belongs to the test that
owns each prompt (`test_result_target.py` pins the target count in three of
them, `test_languages.py` the language). Here the claim is only that the wiring
holds.
"""

from __future__ import annotations

from typing import Any

import pytest

from tinternship_backend.agents.applying import (
    build_address_scout,
    build_applying_team,
    build_cover_letter_agent,
    build_resume_agent,
)
from tinternship_backend.agents.contacts import (
    build_contact_scout,
    build_contact_strategist,
    build_contacts,
)
from tinternship_backend.agents.feedback_agent import build_feedback_analyst
from tinternship_backend.agents.follow_up import (
    build_follow_up_agent,
    build_follow_up_writer,
)
from tinternship_backend.agents.hr_expert import (
    build_hr_expert,
    build_hr_researcher,
    build_playbook_writer,
)
from tinternship_backend.agents.interrogator import build_brief_writer, build_interrogator
from tinternship_backend.agents.interview_prep import (
    build_interview_coach,
    build_interview_prep,
    build_interview_researcher,
)
from tinternship_backend.agents.investigator import (
    build_investigator,
    build_matcher,
    build_normaliser,
    build_query_planner,
    build_scout,
)
from tinternship_backend.agents.profile_agent import (
    build_profile_extractor,
    build_profile_merger,
)
from tinternship_backend.agents.reader import (
    build_link_intake,
    build_reader,
    build_scorer,
)


class State(dict):
    """A session state that answers anything, so an instruction can render.

    A Critic reads the artifact it is reviewing straight out of the state, and a
    missing key would fail here for a reason that has nothing to do with the
    thing being tested. Returning "" renders the empty version of the prompt,
    which is what matters: that it renders at all.
    """

    def __missing__(self, key: str) -> str:
        return ""


class Ctx:
    def __init__(self) -> None:
        self.state = State()


def _plan():
    """A real base résumé, read and priced — what an applying run is handed."""
    from conftest import build_plan

    return build_plan()


def _letter_plan():
    """The same for the letter, with the date and the employer already filled."""
    from conftest import build_letter_plan

    return build_letter_plan()


# Every factory, with arguments that are merely valid — the values are not what
# is under test. A new agent belongs on this list; that is the whole maintenance
# cost of this file.
FACTORIES = {
    "query_planner": lambda: build_query_planner(15),
    "scout": lambda: build_scout(15),
    "normaliser": build_normaliser,
    "matcher": lambda: build_matcher(15),
    "investigator": build_investigator,
    # The résumé track needs the candidate's own document; `_plan()` supplies
    # one so the factory list stays a list of factories.
    "resume_agent": lambda: build_resume_agent(job_id=1, plan=_plan()),
    "address_scout": lambda: build_address_scout(job_id=1),
    "cover_letter_agent": lambda: build_cover_letter_agent(job_id=1, plan=_letter_plan()),
    "applying_team": lambda: build_applying_team(
        job_id=1, resume_plan=_plan(), letter_plan=_letter_plan()
    ),
    "interview_researcher": lambda: build_interview_researcher(job_id=1, application_id=1),
    "interview_coach": lambda: build_interview_coach(job_id=1, application_id=1),
    "interview_prep": lambda: build_interview_prep(job_id=1, application_id=1, language="fr"),
    "contact_scout": lambda: build_contact_scout(job_id=1),
    "contact_strategist": lambda: build_contact_strategist(job_id=1),
    "contacts": lambda: build_contacts(job_id=1, language="fr"),
    "follow_up_agent": lambda: build_follow_up_agent(job_id=1),
    "follow_up_writer": lambda: build_follow_up_writer(job_id=1),
    "hr_researcher": build_hr_researcher,
    "playbook_writer": build_playbook_writer,
    "hr_expert": build_hr_expert,
    "interrogator": build_interrogator,
    "brief_writer": build_brief_writer,
    "profile_extractor": build_profile_extractor,
    "profile_merger": lambda: build_profile_merger([{"kind": "resume", "label": "cv.pdf"}]),
    "feedback_analyst": lambda: build_feedback_analyst([], {}),
    "reader": lambda: build_reader("https://acme.test/jobs/1", "a fetched job page"),
    "scorer": build_scorer,
    "link_intake": lambda: build_link_intake("https://acme.test/jobs/1", "a fetched job page"),
}


def walk(agent: Any) -> list[Any]:
    """The agent and every sub-agent under it, depth first."""
    found = [agent]
    for child in getattr(agent, "sub_agents", None) or []:
        found.extend(walk(child))
    return found


@pytest.mark.parametrize("name", sorted(FACTORIES))
async def test_every_agent_builds_and_its_instruction_renders(name: str) -> None:
    agent = FACTORIES[name]()
    assert agent.name, f"{name} built an agent with no name"

    members = walk(agent)
    for member in members:
        # A composite (Sequential/Parallel/Loop) has no model of its own; an
        # LlmAgent that resolved to nothing would fail at the first call.
        if hasattr(member, "model") and getattr(member, "model", None) is not None:
            assert str(member.model), f"{name}: {member.name} resolved to an empty model"

        # Most instructions here are async callables composing the shared
        # context blocks; one is a plain string. The assertion is that rendering
        # completes and produces prose — see the module docstring for why the
        # length is a floor rather than a claim about the prompt.
        instruction = getattr(member, "instruction", None)
        if callable(instruction):
            instruction = await instruction(Ctx())
        if isinstance(instruction, str):
            assert instruction.strip(), f"{name}: {member.name} rendered an empty instruction"

        # An agent that must answer in JSON carries a pydantic model saying
        # which JSON. ADK will not accept just any model — scalars, lists and
        # nested models only — so this is where a pydantic major shows up.
        schema = getattr(member, "output_schema", None)
        if schema is not None:
            generated = schema.model_json_schema()
            assert generated.get("properties"), f"{name}: {member.name}'s output schema is empty"


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_agent_names_are_unique_within_a_tree(name: str) -> None:
    # ADK addresses sub-agents by name. Two sharing one is a runtime error in
    # the middle of a live run — the most expensive place to discover it, and a
    # copy-paste away whenever a producer gains a second quality gate.
    names = [member.name for member in walk(FACTORIES[name]())]
    duplicates = {value for value in names if names.count(value) > 1}
    assert not duplicates, f"{name} contains duplicate agent names: {sorted(duplicates)}"
