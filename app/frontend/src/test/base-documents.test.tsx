/**
 * The four mandatory documents, on the Account page.
 *
 * A missing base résumé or cover letter is not a feature the candidate has
 * declined to use — it is the reason no application can be produced in that
 * language. So the tests here are mostly about whether the page *says* that: a
 * quiet empty card would leave someone wondering why the Generate button keeps
 * failing.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { CONFIG, renderApp, stubApi } from "./harness";

const UPLOADED = {
  id: 1,
  label: "CV-Alex-FR.docx",
  status: "parsed",
  error: "",
  on_disk: true,
  created_at: "2026-08-28T09:00:00+00:00",
  placeholders: 4,
  page: "About 96% of one page, with room for roughly 266 more characters once the blanks are filled.",
  room: 266,
  crowded: false,
  language_warning: "",
};

/** The same document, on a page with nothing left to give. */
const CROWDED = {
  ...UPLOADED,
  page: "This document already fills about 101% of a page before anything is added, so there is no room to fill the blanks. Free up a line or two and upload it again.",
  room: 0,
  crowded: true,
};

const NONE = { en: null, fr: null };

/** Nothing uploaded: the state a new account starts in. */
function empty() {
  stubApi({
    "/api/config": {
      ...CONFIG,
      base_resumes: NONE,
      base_cover_letters: NONE,
      progress: {
        ...CONFIG.progress,
        has_base_resumes: false,
        has_base_letters: false,
        complete: false,
      },
      warnings: [
        "No fr base résumé uploaded. That is the document an application in fr is built from.",
      ],
    },
    "/api/profile": {
      profile: {},
      has_profile: true,
      sources: [],
      base_resumes: NONE,
      base_cover_letters: NONE,
    },
  });
}

/** Only the French CV uploaded, which is what most of these cards assert on. */
function onlyFrenchCv(document = UPLOADED) {
  stubApi({
    "/api/profile": {
      profile: {},
      has_profile: true,
      sources: [],
      base_resumes: { en: null, fr: document },
      base_cover_letters: NONE,
    },
  });
}

describe("the base document cards", () => {
  beforeEach(() => stubApi());

  it("shows one upload box per document and language", async () => {
    renderApp("/account");

    expect(await screen.findByText("French — CV")).toBeTruthy();
    expect(await screen.findByText("English — résumé")).toBeTruthy();
    expect(await screen.findByText("French — lettre de motivation")).toBeTruthy();
    expect(await screen.findByText("English — cover letter")).toBeTruthy();
  });

  it("marks a missing document as required rather than optional", async () => {
    empty();
    renderApp("/account");

    await waitFor(() =>
      expect(screen.getAllByText(/cannot be produced until this is uploaded/).length).toBe(4),
    );
  });

  it("tells the letter what blanks to leave, which are not the résumé's", async () => {
    renderApp("/account");

    // Once per letter card, and on neither résumé card.
    expect((await screen.findAllByText("[cover_letter_opening_paragraph]")).length).toBe(2);
    expect(
      (await screen.findAllByText(/The date and the employer are filled from the posting itself/))
        .length,
    ).toBe(2);
  });

  it("names the uploaded file once it is there", async () => {
    onlyFrenchCv();
    renderApp("/account");

    expect(await screen.findByText("CV-Alex-FR.docx")).toBeTruthy();
    expect(await screen.findByText("uploaded")).toBeTruthy();
  });

  it("says .docx only, and why blanks are worth leaving in", async () => {
    renderApp("/account");

    const notes = await screen.findAllByText(/the blanks are filled in place/);
    expect(notes.length).toBe(4);
    expect(screen.getAllByText("[a name in brackets]").length).toBe(2);
  });

  it("says how full the page is, because that is what limits the filling", async () => {
    onlyFrenchCv();
    renderApp("/account");

    expect(await screen.findByText(/About 96% of one page/)).toBeTruthy();
    expect(await screen.findByText(/4 blanks to fill/)).toBeTruthy();
  });

  it("warns when a CV is too full to be tailored at all", async () => {
    onlyFrenchCv(CROWDED);
    renderApp("/account");

    expect(await screen.findByText(/free up a line or two/i)).toBeTruthy();
  });

  it("offers Replace rather than Upload once a document exists", async () => {
    onlyFrenchCv();
    renderApp("/account");

    expect(await screen.findByRole("button", { name: "Replace" })).toBeTruthy();
    expect((await screen.findAllByRole("button", { name: "Upload .docx" })).length).toBe(3);
  });
});

describe("the setup checklist", () => {
  it("counts the base résumés as their own step", async () => {
    empty();
    renderApp("/account");

    expect(await screen.findByText("Base résumés")).toBeTruthy();
    expect(
      await screen.findByText("Upload your own Word CV in French and in English."),
    ).toBeTruthy();
  });

  it("counts the cover letters as a step of their own", async () => {
    // A checklist that ticked with the CV uploaded and the letter missing
    // would be saying the setup is done when a run still cannot produce one
    // of its two documents.
    empty();
    renderApp("/account");

    expect(await screen.findByText("Cover letters")).toBeTruthy();
    expect(
      await screen.findByText(
        "Upload your own Word cover letter in both languages — the run fills its blanks.",
      ),
    ).toBeTruthy();
  });

  it("holds the app on the Account page until they exist", async () => {
    empty();
    renderApp("/jobs");

    // `Layout` keeps every main screen on Account until setup is complete.
    expect(await screen.findByText("Base résumés")).toBeTruthy();
  });
});

describe("the two lists the blanks are filled from", () => {
  beforeEach(() => stubApi());

  it("asks for courses and skills as lists, not as prose", async () => {
    renderApp("/account");

    expect(await screen.findByText("Courses you have taken")).toBeTruthy();
    expect(await screen.findByText("Skills you have")).toBeTruthy();
  });

  it("says the résumé can only pick from what is in them", async () => {
    renderApp("/account");

    expect(
      await screen.findByText(/nothing outside this list is ever written onto your CV/),
    ).toBeTruthy();
    expect(await screen.findByText(/will not appear, however well it would have matched/)).toBeTruthy();
  });

  it("marks an empty list as required rather than optional", async () => {
    stubApi({ "/api/profile/lists": { lists: { course: [], skill: [] } } });
    renderApp("/account");

    await waitFor(() =>
      expect(screen.getAllByText(/until this list exists/).length).toBe(2),
    );
  });

  it("takes one item at a time, in both languages", async () => {
    renderApp("/account");

    // One English and one French field per list — what matters is that each
    // list card has both.
    expect((await screen.findAllByText("English")).length).toBe(2);
    expect((await screen.findAllByText("French")).length).toBe(2);
    expect(await screen.findByRole("button", { name: "Add course" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Add skill" })).toBeTruthy();
  });

  it("keeps the Add button disabled until both languages are written", async () => {
    renderApp("/account");

    const add = (await screen.findByRole("button", { name: "Add course" })) as HTMLButtonElement;
    expect(add.disabled).toBe(true);

    const [english, french] = screen.getAllByPlaceholderText(
      /Operations Research|Recherche opérationnelle/,
    );
    fireEvent.change(english, { target: { value: "Probability" } });
    expect((screen.getByRole("button", { name: "Add course" }) as HTMLButtonElement).disabled).toBe(
      true,
    );

    fireEvent.change(french, { target: { value: "Probabilités" } });
    expect((screen.getByRole("button", { name: "Add course" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("shows every saved item in both languages, so a half-translated one is visible", async () => {
    renderApp("/account");

    expect(
      await screen.findByText("Operations Research and Combinatorial Optimisation"),
    ).toBeTruthy();
    expect(
      await screen.findByText("Recherche opérationnelle, optimisation combinatoire"),
    ).toBeTruthy();
    expect(await screen.findByText("Data Analysis")).toBeTruthy();
    expect(await screen.findByText("Analyse de données")).toBeTruthy();
  });

  it("counts them as their own setup step", async () => {
    stubApi({
      "/api/config": {
        ...CONFIG,
        progress: { ...CONFIG.progress, has_lists: false, complete: false },
      },
    });
    renderApp("/account");

    expect(await screen.findByText("Courses & skills")).toBeTruthy();
    expect(
      await screen.findByText("List your coursework and your skills — the résumé picks from them."),
    ).toBeTruthy();
  });
});
