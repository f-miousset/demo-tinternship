"""Filling a blank in a .docx must change the blank and nothing else.

This is the load-bearing test of the whole résumé design. The promise made to
the candidate is *"your document comes back as your document"* — same fonts,
same tab stops, same bold, same number of lines, **same sentences** — and the
only thing standing behind it is this module. So the assertions here are mostly
about what did **not** change.

Since 2026-08-29 that promise is much stronger than it was, and the tests say so
in a specific way: `test_every_character_outside_the_blank_is_identical` compares
the whole document string, because the code slices around the placeholder rather
than re-emitting the line. Under the old re-wording design that assertion could
not have been written.

`check_fills` is the other half — the gate — and everything it refuses is a way
the *shape* of the page would move rather than a matter of taste.
"""

from __future__ import annotations

import io

import pytest
from conftest import build_docx
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from tinternship_backend.services import docx_template as dt


def _document(data: bytes) -> Document:
    return Document(io.BytesIO(data))


def _paragraphs(data: bytes) -> list:
    return list(dt._iter_paragraphs(_document(data)))


class TestReading:
    def test_every_paragraph_gets_an_index_including_the_blank_ones(self):
        blocks = dt.read_blocks(build_docx())

        assert [block.index for block in blocks] == list(range(len(blocks)))
        assert any(block.blank for block in blocks), "the blank spacer must be numbered too"

    def test_a_blank_line_is_numbered_so_the_agent_cannot_miscount(self):
        """If blanks were dropped, every index after one would name the wrong
        paragraph and an edit meant for a bullet would land on a heading."""
        blocks = dt.read_blocks(build_docx(["one", "", "three"]))

        assert [block.text for block in blocks] == ["one", "", "three"]

    def test_table_cells_are_read_in_document_order(self):
        document = Document()
        document.add_paragraph("before")
        table = document.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "left cell"
        table.rows[0].cells[1].text = "right cell"
        document.add_paragraph("after")
        buffer = io.BytesIO()
        document.save(buffer)

        texts = [block.text for block in dt.read_blocks(buffer.getvalue())]

        assert texts.index("before") < texts.index("left cell") < texts.index("after")
        assert "right cell" in texts

    def test_hyperlink_text_is_part_of_its_paragraph(self):
        """`Paragraph.runs` excludes hyperlink runs while `Paragraph.text`
        includes them, so indexing off `runs` would put every edit after a link
        at the wrong character offset — and a résumé always has links."""
        document = Document()
        paragraph = document.add_paragraph("Portfolio: ")
        paragraph.add_run("")  # keep a plain run before the link
        relationship = document.part.relate_to(
            "https://example.com",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            is_external=True,
        )
        import docx.oxml

        paragraph._p.append(
            docx.oxml.parse_xml(
                '<w:hyperlink xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                f'r:id="{relationship}"><w:r><w:t>my site</w:t></w:r></w:hyperlink>'
            )
        )
        buffer = io.BytesIO()
        document.save(buffer)

        blocks = dt.read_blocks(buffer.getvalue())

        assert blocks[0].text == "Portfolio: my site"

    def test_alignment_and_bold_are_read_for_the_preview(self):
        blocks = dt.read_blocks(build_docx())

        assert blocks[0].alignment == "center"
        assert blocks[0].bold is True
        assert blocks[1].bold is False


class TestPlaceholders:
    @pytest.mark.parametrize(
        "text",
        [
            "Objectif : [Poste visé]",
            "Chez {{Entreprise}}",
            "Role: <target role>",
            "Reference: ______",
        ],
    )
    def test_every_syntax_is_detected(self, text):
        assert dt.find_placeholders(text)

    @pytest.mark.parametrize("text", ["Diplôme 2024", "[2024]", "a < b and c > d", "under_score"])
    def test_things_that_are_not_placeholders_are_left_alone(self, text):
        """A bracketed year, a comparison, an identifier. Every pattern requires
        a letter inside precisely so these do not become required work."""
        assert dt.find_placeholders(text) == []

    def test_they_are_reported_in_the_order_they_appear(self):
        found = dt.find_placeholders("Objectif : [Poste] chez {{Entreprise}}")

        assert found == ["[Poste]", "{{Entreprise}}"]


class TestSlots:
    def test_every_placeholder_becomes_a_keyed_slot(self):
        slots = dt.find_slots(dt.read_blocks(build_docx()))

        assert [(slot.key, slot.token, slot.block) for slot in slots] == [
            ("s0", "[Poste visé]", 3),
            ("s1", "[Entreprise]", 3),
        ]

    def test_a_slot_carries_the_line_it_has_to_fit_into(self):
        """A blank is filled *into a sentence*. A model that cannot see the
        sentence writes something ungrammatical in it."""
        slots = dt.find_slots(dt.read_blocks(build_docx()))

        assert slots[0].line == "Objectif : [Poste visé] chez [Entreprise]"

    def test_the_span_is_the_token_and_nothing_else(self):
        slots = dt.find_slots(dt.read_blocks(build_docx()))
        line = slots[0].line

        assert line[slots[0].start : slots[0].end] == "[Poste visé]"
        assert line[slots[1].start : slots[1].end] == "[Entreprise]"

    def test_overlapping_syntaxes_are_one_blank_not_two(self):
        """`[<role>]` matches two patterns. Filling it twice would leave a
        stray bracket on the candidate's page."""
        blocks = dt.read_blocks(build_docx(["Poste : [<role>]"]))

        assert [slot.token for slot in dt.find_slots(blocks)] == ["[<role>]"]


class TestFilling:
    def test_the_number_of_paragraphs_never_changes(self):
        source = build_docx()
        blocks = dt.read_blocks(source)
        slots = dt.find_slots(blocks)

        tailored, _report = dt.apply_fills(
            source, blocks, slots, {"s0": "Stage Data", "s1": "Acme"}
        )

        assert len(dt.read_blocks(tailored)) == len(blocks)

    def test_every_character_outside_the_blank_is_identical(self):
        """The assertion the design exists for: the code slices around the
        placeholder, so the candidate's own words are copied rather than
        re-emitted, and there is nothing left to police."""
        source = build_docx()
        blocks = dt.read_blocks(source)
        slots = dt.find_slots(blocks)

        tailored, _report = dt.apply_fills(
            source, blocks, slots, {"s0": "Stage Data Science", "s1": "Nimbus Labs"}
        )
        after = [block.text for block in dt.read_blocks(tailored)]

        assert after[3] == "Objectif : Stage Data Science chez Nimbus Labs"
        assert after[:3] == [block.text for block in blocks[:3]]
        assert after[4:] == [block.text for block in blocks[4:]]

    def test_a_fill_inherits_the_formatting_of_the_run_it_lands_in(self):
        """The placeholder sits in a bold run, so what replaces it is bold —
        without anything here knowing that it was."""
        document = Document()
        paragraph = document.add_paragraph()
        paragraph.add_run("Poste : ")
        paragraph.add_run("[Poste visé]").bold = True
        buffer = io.BytesIO()
        document.save(buffer)
        source = buffer.getvalue()
        blocks = dt.read_blocks(source)

        tailored, _report = dt.apply_fills(
            source, blocks, dt.find_slots(blocks), {"s0": "Ingénieur ML"}
        )

        runs = _paragraphs(tailored)[0].runs
        assert [run.text for run in runs] == ["Poste : ", "Ingénieur ML"]
        assert runs[0].bold is not True
        assert runs[1].bold is True

    def test_an_untouched_run_keeps_its_formatting(self):
        """The employer is bold and the location beside it is not. Writing a
        whole new line into the first run — the obvious implementation — would
        make the location bold too."""
        source = build_docx()

        tailored, _report = dt.apply_lines(source, {4: "Acme\tLyon, France"})

        runs = _paragraphs(tailored)[4].runs
        assert [run.text for run in runs] == ["Acme", "\tLyon, France"]
        assert runs[0].bold is True
        assert runs[1].bold is not True

    def test_a_tab_survives_the_round_trip(self):
        source = build_docx()

        tailored, _report = dt.apply_lines(source, {4: "Acme Corp\tLyon, France"})

        assert "w:tab" in _paragraphs(tailored)[4]._p.xml
        assert dt.read_blocks(tailored)[4].text == "Acme Corp\tLyon, France"

    def test_paragraph_alignment_and_style_are_untouched(self):
        source = build_docx()
        blocks = dt.read_blocks(source)

        tailored, _report = dt.apply_fills(
            source, blocks, dt.find_slots(blocks), {"s0": "Stage", "s1": "Acme"}
        )
        after = dt.read_blocks(tailored)

        assert after[0].alignment == "center"
        assert after[0].bold is True

    def test_the_document_title_is_set_without_touching_the_page(self):
        source = build_docx()
        before = [block.text for block in dt.read_blocks(source)]

        tailored, _report = dt.apply_lines(source, {}, title="CV — Stage ML")

        assert _document(tailored).core_properties.title == "CV — Stage ML"
        assert [block.text for block in dt.read_blocks(tailored)] == before

    def test_a_line_naming_no_such_block_is_skipped_not_raised(self):
        """An artifact can outlive the document it was written against."""
        tailored, report = dt.apply_lines(build_docx(), {999: "nowhere"})

        assert report.skipped == {999: "no such block"}
        assert tailored[:2] == b"PK"

    def test_an_unfilled_slot_keeps_its_token_rather_than_vanishing(self):
        """`check_fills` is what refuses this. Leaving the token visible means
        the preview shows the blank that was missed, instead of a sentence that
        quietly lost a word."""
        blocks = dt.read_blocks(build_docx())
        slots = dt.find_slots(blocks)

        lines = dt.filled_lines(blocks, slots, {"s0": "Stage Data"})

        assert lines[3] == "Objectif : Stage Data chez [Entreprise]"


class TestTheGate:
    def _checked(self, fills, lines=None):
        blocks = dt.read_blocks(build_docx(lines))
        slots = dt.find_slots(blocks)
        return dt.check_fills(blocks, slots, fills)

    def test_a_complete_set_of_fills_passes(self):
        assert self._checked({"s0": "Stage Data Science", "s1": "Nimbus Labs"}) == []

    def test_a_blank_left_unfilled_is_refused(self):
        problems = self._checked({"s0": "Stage Data Science"})

        assert any("left unfilled" in problem for problem in problems)

    def test_an_empty_fill_is_refused(self):
        problems = self._checked({"s0": "Stage", "s1": "   "})

        assert any("came back empty" in problem for problem in problems)

    def test_a_fill_that_is_itself_a_placeholder_is_refused(self):
        problems = self._checked({"s0": "Stage", "s1": "[to be completed]"})

        assert any("another placeholder" in problem for problem in problems)

    def test_a_tab_in_a_fill_is_refused(self):
        problems = self._checked({"s0": "Stage\tData", "s1": "Acme"})

        assert any("contains a tab" in problem for problem in problems)

    def test_a_line_break_in_a_fill_is_refused(self):
        problems = self._checked({"s0": "Stage\nData", "s1": "Acme"})

        assert any("line break" in problem for problem in problems)

    def test_a_slot_the_document_does_not_have_is_refused(self):
        problems = self._checked({"s0": "Stage", "s1": "Acme", "s9": "nowhere"})

        assert any("no slot 's9'" in problem for problem in problems)

    def test_a_fill_over_its_budget_is_refused(self):
        blocks = dt.read_blocks(build_docx())
        slots = dt.with_budgets(dt.find_slots(blocks), {"s0": 20, "s1": 20})

        problems = dt.check_fills(blocks, slots, {"s0": "x" * 40, "s1": "Acme"})

        assert any("against a budget of 20" in problem for problem in problems)

    def test_a_document_with_no_blanks_needs_no_fills(self):
        assert self._checked({}, lines=["Alex Martin", "Python, SQL"]) == []


class TestTailoredText:
    def test_it_reads_as_the_finished_page(self):
        blocks = dt.read_blocks(build_docx())
        slots = dt.find_slots(blocks)

        text = dt.tailored_text(
            blocks, dt.filled_lines(blocks, slots, {"s0": "Stage Data", "s1": "Acme"})
        )

        assert "Objectif : Stage Data chez Acme" in text
        assert "[Poste visé]" not in text
        assert "Alex Martin" in text


class TestTheCeilingMatchesTheSchema:
    def test_the_slot_limit_is_the_size_of_the_key_enum(self):
        """A document with more blanks than there are slot keys has blanks the
        Tailor has no name for — so it cannot fill them, and nothing would say
        why."""
        from tinternship_backend.agents.schemas import MAX_SLOTS, SLOT_KEYS

        assert MAX_SLOTS == dt.MAX_SLOTS
        assert tuple(SLOT_KEYS) == dt.SLOT_KEYS

    def test_a_document_past_the_ceiling_is_truncated_not_lost(self):
        lines = [f"Ligne [blanc {index}]" for index in range(dt.MAX_SLOTS + 5)]
        slots = dt.find_slots(dt.read_blocks(build_docx(lines)))

        assert len(slots) == dt.MAX_SLOTS


class TestNotEditable:
    def test_a_paragraph_holding_a_picture_is_never_rewritten(self):
        """`Run.text = …` replaces every child of the run, so a run holding a
        drawing loses the drawing. Better to leave the line alone."""
        document = Document()
        document.add_paragraph("safe line")
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        run.add_picture(io.BytesIO(_PNG), width=100000)
        buffer = io.BytesIO()
        document.save(buffer)
        source = buffer.getvalue()

        blocks = dt.read_blocks(source)
        assert blocks[1].editable is False

        _tailored, report = dt.apply_lines(source, {1: "text"})
        assert report.skipped == {1: "holds a picture or a field"}

    def test_a_blank_inside_a_picture_paragraph_is_refused_rather_than_filled(self):
        document = Document()
        paragraph = document.add_paragraph()
        paragraph.add_run().add_picture(io.BytesIO(_PNG), width=100000)
        paragraph.add_run("[Poste visé]")
        buffer = io.BytesIO()
        document.save(buffer)

        blocks = dt.read_blocks(buffer.getvalue())
        slots = dt.find_slots(blocks)

        problems = dt.check_fills(blocks, slots, {"s0": "Stage ML"})
        assert any("picture or a field" in problem for problem in problems)


# A 1×1 transparent PNG, built rather than pasted: the smallest thing
# python-docx will accept as an image, and the point is only that the paragraph
# holds a `w:drawing`.
def _make_png() -> bytes:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


_PNG = _make_png()
