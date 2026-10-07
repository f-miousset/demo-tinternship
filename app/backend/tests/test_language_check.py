"""A French document must not have English left in it — and vice versa.

This is the test for the complaint that started the 2026-08-28 rewrite: French
résumés kept arriving with English in them. The detector is a hard check, so the
interesting cases are not the obvious ones. They are the **false positives**: a
perfectly good French CV is full of English technical vocabulary, and a detector
that rejects "Machine Learning" would push the model to translate exactly the
strings the ATS searches for.

So the shape of this file is deliberate: the first thing it asserts is what must
*pass*.

The same marker lists answer a second question since 2026-09-18, at the other
end of the app: `detect` and `posting_language` decide which language an
application package is written in, by reading the posting. Nobody is asked, so
the guess is the answer — `TestGuessingAPostingsLanguage` is where it has to be
right.
"""

from __future__ import annotations

import pytest

from tinternship_backend.services.language_check import (
    DISTINCT_THRESHOLD,
    detect,
    foreign_markers,
    posting_language,
    wrong_language,
)

# A genuinely good French CV. Every English string in it is a proper noun, a
# framework, or the name the field uses for itself in French too.
GOOD_FRENCH = """
Alex Martin
Ingénieur en apprentissage automatique
FORMATION
INSA Lyon — Diplôme d'ingénieur, spécialité Machine Learning et Data Science
Master of Science, Computer Science
EXPÉRIENCE PROFESSIONNELLE
Stage Data Scientist chez Acme — conception d'un pipeline de Deep Learning
Développement d'un dashboard temps réel (Python, Kafka, Docker, Kubernetes)
Product Owner adjoint sur une plateforme de Business Intelligence
COMPÉTENCES
Python, SQL (PostgreSQL), Natural Language Processing (NLP), Cloud Computing
Scrum, Agile, Git, CI/CD, Amazon Web Services (AWS)
"""

GOOD_ENGLISH = """
Alex Martin
Machine Learning Engineer
EDUCATION
INSA Lyon — Engineering degree, Computer Science
EXPERIENCE
Data Science Intern at Banque de France — built a real-time ingestion pipeline
Worked on the Crédit Agricole risk platform
SKILLS
Python, SQL (PostgreSQL), Natural Language Processing (NLP)
"""


class TestWhatMustPass:
    def test_a_good_french_cv_full_of_english_technical_terms_is_clean(self):
        assert wrong_language(GOOD_FRENCH, "fr") == ""

    def test_a_good_english_cv_with_french_employer_names_is_clean(self):
        assert wrong_language(GOOD_ENGLISH, "en") == ""

    @pytest.mark.parametrize(
        "line",
        [
            "Master of Science, Computer Science",
            "Deep Learning et Computer Vision",
            "Certification Scrum Product Owner",
            "Stage chez Bank of America",
        ],
    )
    def test_one_stray_marker_is_a_degree_name_not_a_sentence(self, line):
        """`of` is a marker and "Master of Science" is a degree. One marker is
        never evidence; the threshold is what makes the check usable."""
        assert wrong_language(line, "fr") == ""

    def test_an_empty_document_is_clean(self):
        assert wrong_language("", "fr") == ""


class TestWhatMustFail:
    def test_an_english_sentence_in_a_french_cv_is_caught(self):
        text = GOOD_FRENCH + "\nBuilt and maintained the data pipeline that the whole team uses.\n"

        problem = wrong_language(text, "fr")

        assert "still has English in it" in problem

    def test_a_french_sentence_in_an_english_cv_is_caught(self):
        text = GOOD_ENGLISH + "\nConception et mise en oeuvre d'une architecture de données.\n"

        assert "still has French in it" in wrong_language(text, "en")

    def test_an_english_sentence_left_behind_is_caught(self):
        """The exact observed failure: most of the CV translated, the connective
        tissue of one line not.

        The heading on the third line is *not* what catches it any more — a run
        of markers between two capitalised words reads as a name now, and
        "Work Experience and Skills" has the shape of one. The bullet does.
        """
        text = "FORMATION\nINSA Lyon\nWork Experience and Skills\nStage chez Acme with the team"

        assert wrong_language(text, "fr") != ""

    def test_the_message_names_the_actual_words(self):
        """A model told *which* words can fix them. A model told there is a
        problem somewhere rewrites the whole document."""
        text = GOOD_FRENCH + "\nI have been working with the team on this for two years.\n"

        problem = wrong_language(text, "fr")

        assert '"the"' in problem
        assert "with" in problem

    def test_the_message_says_to_keep_the_proper_nouns(self):
        text = GOOD_FRENCH + "\nBuilt and maintained the data pipeline that the team uses.\n"

        problem = wrong_language(text, "fr")

        assert "Keep proper nouns" in problem
        assert "keyword strings" in problem


class TestWhatIsNotProse:
    """The three false alarms of 2026-09-10, each on a correctly filed document.

    All three come from the same wrong assumption: that everything on a CV is a
    sentence. A blank's name, a link and an employer's name are none of them
    written in the language of the page.
    """

    def test_a_blanks_name_is_not_the_documents_language(self):
        """The Account page asks for `[list_of_relevant_skills]`, so a French CV
        that followed the instructions carries `of` twice."""
        text = "Cours suivis : [list_of_relevant_courses]\nTechniques : [list_of_relevant_skills]"

        assert foreign_markers(text, "fr") == {}
        assert wrong_language(text, "fr") == ""

    def test_a_link_is_not_a_sentence(self):
        """`linkedin.com/in/...` is on both CVs and tokenises to "in"."""
        text = "alex.martin@example.org | linkedin.com/in/alex-martin | github.com/alexm"

        assert foreign_markers(text, "fr") == {}

    def test_a_french_institution_keeps_its_own_name_on_an_english_cv(self):
        """Nine `de` and one `la`, all of them one university and one event —
        the real English résumé, flagged as French until this rule existed."""
        text = (
            "AI Engineering student at Université de Technologie de Lyon (UTL)\n"
            "Université de Technologie de Lyon (UTL) — Lyon, France\n"
            "Lead Organizer of the Nuits de la Recherche"
        )

        assert foreign_markers(text, "en") == {}

    def test_a_sentence_around_a_name_is_still_caught(self):
        """The rule cuts out the middle of a name, not the words either side of
        it: prose puts a lowercase word next to at least one of its markers."""
        text = "Stage à l'Université de Technologie de Lyon, avec une équipe de six"

        assert wrong_language(text, "en") != ""


class TestTheThreshold:
    def test_it_takes_two_distinct_markers(self):
        assert DISTINCT_THRESHOLD == 2
        assert wrong_language("Rapport of synthèse", "fr") == ""
        assert wrong_language("Rapport of the synthèse", "fr") != ""

    def test_or_three_occurrences_of_one(self):
        assert wrong_language("Analyse of données, conception of pipelines, revue of code", "fr") != ""

    def test_counts_are_reported_for_the_caller_to_reason_about(self):
        counts = foreign_markers("the team and the project", "fr")

        assert counts["the"] == 2
        assert counts["and"] == 1


class TestRobustness:
    def test_a_typographic_apostrophe_reads_as_french(self):
        """Word inserts `’`, not `'`, so `d’une` has to count."""
        assert foreign_markers("Conception d’une architecture", "en")

    def test_an_unsupported_language_code_falls_back_rather_than_raising(self):
        """A document in the wrong language is recoverable; a 500 mid-stream on
        the generate button is not."""
        assert wrong_language(GOOD_ENGLISH, "klingon") == ""


# Four postings, each a shape the guess has to get right. They are written the
# way the Reader writes one — the posting's own prose, in the posting's own
# language — because that is what it is given.
FRENCH_POSTING = {
    "title": "Stage Data Scientist H/F",
    "summary": "Stage de six mois dans l'équipe Data, à Paris.",
    "description": (
        "Au sein de notre équipe Data, vous participerez à la conception et à la mise en "
        "production de modèles de Machine Learning. Vous travaillerez avec les équipes "
        "produit pour industrialiser nos pipelines."
    ),
    "requirements": ["Étudiant en dernière année d'école d'ingénieur", "Maîtrise de Python"],
    "nice_to_have": ["Une première expérience en MLOps"],
}

ENGLISH_POSTING = {
    "title": "ML Research Intern",
    "summary": "Six months on the perception team, in Paris.",
    "description": (
        "You will join the perception team and work on representation learning for our "
        "robotics stack. The role is a six-month internship and you will be supervised "
        "by a senior researcher."
    ),
    "requirements": ["Enrolled in a Master's programme", "Strong Python"],
    "nice_to_have": ["A publication"],
}

# The case the whole function-word premise exists for, pointed the other way: a
# French posting is *full* of English, and none of it is a sentence.
FRENCH_POSTING_IN_ENGLISH_JARGON = {
    "title": "Stage Machine Learning Engineer",
    "summary": "Feature store, streaming pipelines et monitoring.",
    "description": (
        "Vous rejoindrez notre squad Data Platform pour travailler sur le feature store, "
        "les pipelines de streaming et le monitoring de nos modèles en production. Vous "
        "serez accompagné par un Senior Data Engineer."
    ),
    "requirements": ["Python, Spark, Airflow, Kubernetes, MLflow, dbt, Snowflake, Terraform"],
    "nice_to_have": [],
}

# And the mirror: an English posting whose employer, team and address are French
# names. Names are where a naive counter goes wrong in this direction.
ENGLISH_POSTING_AT_A_FRENCH_EMPLOYER = {
    "title": "Data Science Intern",
    "company": "Société Générale Corporate & Investment Banking",
    "summary": "Pricing models with the Quantitative Research team.",
    "description": (
        "You will work with the Quantitative Research team in La Défense on pricing "
        "models. The internship runs for six months and is based at Tours Société "
        "Générale, and you will report to the head of Data Science."
    ),
    "requirements": ["Enrolled in a Master's programme"],
    "nice_to_have": [],
}


class TestGuessingAPostingsLanguage:
    """You answer a posting in the language it was advertised in.

    Nobody is asked any more, so a wrong guess is two documents in the wrong
    language rather than a mis-selected radio button. The cases that matter are
    the two where the languages are mixed — which is most of this market.
    """

    def test_a_french_posting_is_french(self):
        assert posting_language(FRENCH_POSTING) == "fr"

    def test_an_english_posting_is_english(self):
        assert posting_language(ENGLISH_POSTING) == "en"

    def test_english_technical_vocabulary_does_not_make_a_posting_english(self):
        # `feature store`, `streaming`, `monitoring`, `Senior Data Engineer`,
        # eight product names — and not one function word among them, which is
        # the entire reason this file counts what it counts.
        assert posting_language(FRENCH_POSTING_IN_ENGLISH_JARGON) == "fr"

    def test_a_french_employers_name_does_not_make_a_posting_french(self):
        assert posting_language(ENGLISH_POSTING_AT_A_FRENCH_EMPLOYER) == "en"

    def test_it_reads_a_row_as_well_as_a_dict(self):
        """The two callers hold different shapes of the same posting."""

        class Row:
            title = FRENCH_POSTING["title"]
            summary = FRENCH_POSTING["summary"]
            description = FRENCH_POSTING["description"]
            requirements = FRENCH_POSTING["requirements"]
            nice_to_have = FRENCH_POSTING["nice_to_have"]

        assert posting_language(Row()) == "fr"

    def test_the_company_is_not_read_at_all(self):
        """A name is not evidence, so it is not in `POSTING_PROSE`."""
        assert posting_language({"company": "Société Générale de Surveillance"}) == "en"

    @pytest.mark.parametrize("text", ["", "Stage Data Scientist H/F", "   "])
    def test_a_text_that_has_not_said_falls_back_to_the_default(self, text):
        # A title is not prose and carries no function words either way. Falling
        # back beats a coin toss: there is no third package language to choose,
        # and the picker on the application page is one control away.
        assert detect(text) == "en"

    def test_a_language_the_app_does_not_write_in_falls_back_too(self):
        german = (
            "Praktikum Softwareentwicklung. Wir suchen einen Praktikanten für unser "
            "Team in Berlin. Du arbeitest mit modernen Technologien."
        )
        assert detect(german) == "en"

    def test_a_posting_with_nothing_readable_does_not_raise(self):
        assert posting_language({}) == "en"
        assert posting_language(None) == "en"
