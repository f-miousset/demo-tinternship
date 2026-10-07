"""Every link this feature hands over either cannot be wrong or was proved right.

Two halves, and the split is the whole design. The **constructed** half — the
LinkedIn people searches — is built in Python from the employer's name, the
candidate's own schools and the posting's vocabulary, so no model ever writes a
URL and none of them can 404. The **discovered** half — a profile URL, a page
that names somebody — is fetched, and kept only when the page came back live
*and*, for a profile, titled with that person's name.

Nothing here touches the network: `check_pages` is stubbed with the responses
LinkedIn was measured to give on 2026-08-29 (a live profile titles itself with
the person's name and employer; an invented slug answers 999).
"""

from __future__ import annotations

import pytest

from tinternship_backend.agents.schemas import EducationEntry, MasterProfile
from tinternship_backend.services import outreach
from tinternship_backend.services.outreach import PageCheck
from tinternship_backend.services.profile_store import save_profile


def _profile(schools: list[str]) -> None:
    save_profile(
        MasterProfile(
            full_name="Alex Martin",
            education=[
                EducationEntry(degree="MSc", institution=school) for school in schools
            ],
        )
    )


class TestLinksThatCannotBeWrong:
    """A search URL opens a search. There is nothing in it to be wrong about."""

    def test_a_multi_word_employer_is_quoted_or_it_matches_everyone(self):
        # Unquoted, `Nimbus Labs` matches everyone at Nimbus and everyone in a
        # lab — which is a list of strangers, not a list of contacts.
        assert outreach.phrase("Nimbus Labs") == '"Nimbus Labs"'
        assert outreach.phrase("Datadog") == "Datadog"
        assert outreach.phrase('"already quoted"') == '"already quoted"'

    def test_the_search_url_is_encoded_and_points_at_people(self):
        url = outreach.people_search('"Nimbus Labs" recruiter')
        assert url.startswith("https://www.linkedin.com/search/results/people/?keywords=")
        assert "%22Nimbus+Labs%22" in url
        assert " " not in url

    def test_an_empty_query_produces_no_link_at_all(self):
        """Better nothing than a search for nothing: `?keywords=` opens the
        whole of LinkedIn."""
        assert outreach.people_search("   ") == ""
        assert outreach.company_url("") == ""

    def test_the_contract_words_are_stripped_from_the_role(self):
        """Searching for "Machine Learning Intern (H/F)" finds interns. The
        people worth contacting are not interns."""
        assert outreach.role_terms("Machine Learning Intern (H/F)", []) == "Machine Learning"
        assert outreach.role_terms("Stage - Data Engineer", []) == "Data Engineer"

    def test_a_postings_own_keyword_beats_its_title(self):
        assert outreach.role_terms("Internship (F/H)", ["computer vision"]) == "computer vision"

    def test_the_six_standard_angles_exist_whatever_the_research_found(self):
        angles = outreach.standard_angles(
            "Nimbus Labs", "Machine Learning Intern", ["computer vision"], ["INSA Lyon"]
        )
        keys = [angle.key for angle in angles]
        assert keys == ["alumni", "recruiters", "campus", "team", "manager", "alumni_field"]
        # Every one of them is a link, and every one of them names the employer.
        assert all(angle.url.startswith("https://www.linkedin.com/search/") for angle in angles)
        assert all("Nimbus" in angle.keywords or "INSA" in angle.keywords for angle in angles)

    def test_the_alumni_search_names_the_candidates_own_school(self):
        angles = outreach.standard_angles("Nimbus Labs", "ML Intern", [], ["INSA Lyon"])
        alumni = next(angle for angle in angles if angle.key == "alumni")
        assert '"INSA Lyon"' in alumni.keywords
        assert '"Nimbus Labs"' in alumni.keywords

    def test_no_employer_means_no_searches_rather_than_broken_ones(self):
        assert outreach.standard_angles("", "ML Intern", [], ["INSA Lyon"]) == []

    def test_the_schools_come_from_the_profile_not_from_a_model(self):
        _profile(["INSA Lyon", "Université de Lyon", "INSA Lyon"])
        # De-duplicated, in profile order, because an alumni search built on a
        # misremembered school name finds strangers.
        assert outreach.school_names() == ["INSA Lyon", "Université de Lyon"]


class TestReadingAProfileUrl:
    def test_a_country_prefixed_host_is_still_linkedin(self):
        """Search results cite `fr.linkedin.com` about as often as `www.` — it
        is which edge served the page, not a different site."""
        assert (
            outreach.canonical_profile("https://fr.linkedin.com/in/claire-dupont-91/?trk=x")
            == "https://www.linkedin.com/in/claire-dupont-91"
        )

    def test_something_that_is_not_a_profile_is_not_treated_as_one(self):
        assert outreach.canonical_profile("https://example.com/in/claire") == ""
        assert outreach.canonical_profile("https://www.linkedin.com/company/nimbus") == ""

    def test_the_page_title_is_what_proves_whose_profile_it_is(self):
        assert outreach.name_matches(
            "Claire Dupont", "Claire Dupont - Head of Data at Nimbus | LinkedIn"
        )
        # The same surname, a different person: exactly the failure this exists
        # for, because the candidate would message a stranger.
        assert not outreach.name_matches("Claire Dupont", "Marc Dupont - CFO | LinkedIn")
        assert not outreach.name_matches("Claire Dupont", "Sign Up | LinkedIn")

    def test_accents_and_middle_names_do_not_break_a_real_match(self):
        assert outreach.name_matches("Jean Müller", "Jean Muller - CTO | LinkedIn")
        assert outreach.name_matches("Marie Claire Dubois", "Marie Dubois - Recruteuse")


def _stub(monkeypatch, pages: dict[str, PageCheck]):
    async def fake(urls):
        return {url: pages[url] for url in urls if url in pages}

    monkeypatch.setattr(outreach, "check_pages", fake)


def live(url: str, title: str = "") -> PageCheck:
    return PageCheck(url=url, verdict=outreach.LIVE, http_status=200, title=title)


class TestProvingWhatTheScoutFound:
    @pytest.fixture(autouse=True)
    def _schools(self):
        _profile(["INSA Lyon"])

    async def _resolve(self, plan: dict) -> dict:
        return await outreach.resolve(
            plan, company="Nimbus Labs", title="ML Intern", keywords=[]
        )

    async def test_a_profile_the_page_confirms_is_kept(self, monkeypatch):
        _stub(
            monkeypatch,
            {
                "https://www.linkedin.com/in/claire-dupont": live(
                    "https://www.linkedin.com/in/claire-dupont",
                    "Claire Dupont - Campus Manager at Nimbus Labs | LinkedIn",
                ),
                "https://nimbus.test/team": live("https://nimbus.test/team", "The team"),
            },
        )
        result = await self._resolve(
            {
                "people": [
                    {
                        "name": "Claire Dupont",
                        "role": "Campus Manager",
                        "linkedin_url": "https://www.linkedin.com/in/claire-dupont/",
                        "evidence_url": "https://nimbus.test/team",
                    }
                ]
            }
        )
        person = result["people"][0]
        assert person["profile_status"] == "verified"
        assert person["linkedin_url"] == "https://www.linkedin.com/in/claire-dupont"
        assert result["checked"]["profiles_verified"] == 1

    async def test_a_profile_that_is_somebody_else_is_thrown_away(self, monkeypatch):
        _stub(
            monkeypatch,
            {
                "https://www.linkedin.com/in/claire-dupont": live(
                    "https://www.linkedin.com/in/claire-dupont",
                    "Marc Dupont - CFO at Somewhere | LinkedIn",
                ),
                "https://nimbus.test/team": live("https://nimbus.test/team", "The team"),
            },
        )
        result = await self._resolve(
            {
                "people": [
                    {
                        "name": "Claire Dupont",
                        "linkedin_url": "https://www.linkedin.com/in/claire-dupont",
                        "evidence_url": "https://nimbus.test/team",
                    }
                ]
            }
        )
        person = result["people"][0]
        assert person["profile_status"] == "mismatch"
        assert person["linkedin_url"] == ""
        # She is still worth writing to — the page that named her is real — so
        # she keeps a search that finds her rather than a link to a stranger.
        assert "Claire+Dupont" in person["search_url"].replace("%22", "")

    async def test_an_unprovable_profile_becomes_a_search_rather_than_a_gamble(
        self, monkeypatch
    ):
        """999 is LinkedIn refusing, which is also what it does when
        rate-limiting. It is never read as "this person does not exist" — and
        the URL is dropped either way, because unproved is unproved."""
        _stub(
            monkeypatch,
            {
                "https://www.linkedin.com/in/invented-person": PageCheck(
                    url="https://www.linkedin.com/in/invented-person",
                    verdict=outreach.UNKNOWN,
                    http_status=999,
                ),
                "https://nimbus.test/blog": live("https://nimbus.test/blog", "Engineering"),
            },
        )
        result = await self._resolve(
            {
                "people": [
                    {
                        "name": "Invented Person",
                        "linkedin_url": "https://www.linkedin.com/in/invented-person",
                        "evidence_url": "https://nimbus.test/blog",
                    }
                ]
            }
        )
        assert result["people"][0]["profile_status"] == "unproved"
        assert result["people"][0]["linkedin_url"] == ""
        assert result["people"][0]["search_url"]

    async def test_somebody_standing_on_nothing_is_dropped_and_said_so(self, monkeypatch):
        """No verified profile and a dead source page: there is no evidence this
        person exists at all. The list shrinks, and the page says why — a list
        that silently shrank is indistinguishable from a search that found less."""
        _stub(
            monkeypatch,
            {
                "https://nimbus.test/gone": PageCheck(
                    url="https://nimbus.test/gone", verdict=outreach.GONE, http_status=404
                )
            },
        )
        result = await self._resolve(
            {"people": [{"name": "Ghost Person", "evidence_url": "https://nimbus.test/gone"}]}
        )
        assert result["people"] == []
        assert result["dropped"][0]["name"] == "Ghost Person"
        assert "gone" in result["dropped"][0]["reason"]
        assert result["checked"]["dropped"] == 1

    async def test_a_verified_profile_carries_someone_whose_source_died(self, monkeypatch):
        """The page that named them has gone, but their profile is live and
        theirs. That is stronger evidence than the source was."""
        _stub(
            monkeypatch,
            {
                "https://www.linkedin.com/in/claire-dupont": live(
                    "https://www.linkedin.com/in/claire-dupont", "Claire Dupont - Nimbus Labs"
                ),
                "https://nimbus.test/gone": PageCheck(
                    url="https://nimbus.test/gone", verdict=outreach.GONE, http_status=404
                ),
            },
        )
        result = await self._resolve(
            {
                "people": [
                    {
                        "name": "Claire Dupont",
                        "linkedin_url": "https://www.linkedin.com/in/claire-dupont",
                        "evidence_url": "https://nimbus.test/gone",
                    }
                ]
            }
        )
        assert result["people"][0]["profile_status"] == "verified"
        assert result["people"][0]["evidence_url"] == ""

    async def test_verified_people_sort_above_the_rest(self, monkeypatch):
        _stub(
            monkeypatch,
            {
                "https://nimbus.test/team": live("https://nimbus.test/team", "Team"),
                "https://www.linkedin.com/in/real": live(
                    "https://www.linkedin.com/in/real", "Bea Real - Nimbus Labs"
                ),
            },
        )
        result = await self._resolve(
            {
                "people": [
                    {"name": "Ann Unproved", "evidence_url": "https://nimbus.test/team"},
                    {
                        "name": "Bea Real",
                        "linkedin_url": "https://www.linkedin.com/in/real",
                        "evidence_url": "https://nimbus.test/team",
                    },
                ]
            }
        )
        assert [person["name"] for person in result["people"]] == ["Bea Real", "Ann Unproved"]

    async def test_a_company_slug_that_404s_never_becomes_a_link(self, monkeypatch):
        """Measured: LinkedIn answers an invented company slug with a 404, so
        this one is genuinely checkable — and checked."""
        _stub(
            monkeypatch,
            {
                "https://www.linkedin.com/company/invented/": PageCheck(
                    url="https://www.linkedin.com/company/invented/",
                    verdict=outreach.GONE,
                    http_status=404,
                )
            },
        )
        result = await self._resolve({"company_linkedin_slug": "invented"})
        assert result["company"] == {}

    async def test_a_real_company_slug_brings_its_employee_pages_with_it(self, monkeypatch):
        _stub(
            monkeypatch,
            {
                "https://www.linkedin.com/company/nimbus-labs/": live(
                    "https://www.linkedin.com/company/nimbus-labs/", "Nimbus Labs | LinkedIn"
                )
            },
        )
        result = await self._resolve({"company_linkedin_slug": "nimbus-labs"})
        assert result["company"]["people_url"].endswith("/company/nimbus-labs/people/")
        assert "recruiter" in result["company"]["recruiters_url"]

    async def test_the_searches_are_the_floor_when_the_research_found_nobody(
        self, monkeypatch
    ):
        """A run that named nobody still saves something worth opening. This is
        why the shortlist being empty is not an error."""
        _stub(monkeypatch, {})
        result = await self._resolve({"people": [], "notes": "No named staff are published."})
        assert result["people"] == []
        assert len(result["angles"]) == 6
        assert all(angle["url"] for angle in result["angles"])

    async def test_the_scouts_own_angles_are_appended_but_never_duplicated(
        self, monkeypatch
    ):
        _stub(monkeypatch, {})
        standard = outreach.standard_angles("Nimbus Labs", "ML Intern", [], ["INSA Lyon"])
        result = await self._resolve(
            {
                "angles": [
                    {"label": "The parent group", "keywords": '"Nimbus Group" recrutement'},
                    # The same query the app already built: adds nothing.
                    {"label": "Recruiters", "keywords": standard[1].keywords},
                ]
            }
        )
        labels = [angle["label"] for angle in result["angles"]]
        assert "The parent group" in labels
        assert labels.count("Recruiters") == 0
        assert result["angles"][-1]["url"].startswith("https://www.linkedin.com/search/")

    async def test_a_link_the_scout_typed_into_an_angle_is_not_used_as_one(
        self, monkeypatch
    ):
        """Angles are keywords; the URL is built here. Even if a model puts a
        URL in the keywords field, what ships is a search for that text."""
        _stub(monkeypatch, {})
        result = await self._resolve(
            {"angles": [{"label": "x", "keywords": "https://linkedin.com/in/made-up"}]}
        )
        assert all(
            angle["url"].startswith("https://www.linkedin.com/search/results/people/")
            for angle in result["angles"]
        )
