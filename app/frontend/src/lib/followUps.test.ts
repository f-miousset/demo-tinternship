/**
 * What the follow-up panel puts on the clipboard and into the mail client.
 *
 * This is the one place in the app where generated text leaves it and is sent
 * to a company under the user's name, so the two rules are worth a test: the
 * advice written *to the user* never travels with the message, and the mail
 * opens with no recipient — the agent is forbidden from inventing an address,
 * so the app does not have one to fill in.
 */
import { describe, expect, it } from "vitest";

import { emailBody, emailText, mailtoHref } from "./followUps";
import type { FollowUpEmail } from "./types";

const EMAIL: FollowUpEmail = {
  recipient: "",
  to_hint: "Reply inside the original thread rather than to a new address.",
  subject: "  Following up on my application  ",
  greeting: "Bonjour,",
  paragraphs: ["  I applied on 2 June.  ", "", "Happy to answer any question."],
  sign_off: "Bien cordialement,",
  signature: "Alex Martin",
  language: "fr",
  word_count: 84,
  facts_used: ["applied 2026-06-02"],
  send_notes: ["Send on a Tuesday morning."],
};

describe("emailBody", () => {
  it("joins the parts with blank lines and drops the empty ones", () => {
    expect(emailBody(EMAIL)).toBe(
      [
        "Bonjour,",
        "I applied on 2 June.",
        "Happy to answer any question.",
        "Bien cordialement,",
        "Alex Martin",
      ].join("\n\n"),
    );
  });

  it("never carries the notes written to the user", () => {
    const body = emailBody(EMAIL);
    expect(body).not.toContain(EMAIL.to_hint);
    expect(body).not.toContain(EMAIL.send_notes[0]);
  });

  it("survives a draft with no paragraphs", () => {
    expect(emailBody({ ...EMAIL, paragraphs: undefined as unknown as string[] })).toContain("Bonjour,");
  });
});

describe("emailText", () => {
  it("labels the subject in the language the draft was written in", () => {
    expect(emailText(EMAIL).startsWith("Objet: Following up on my application\n\n")).toBe(true);
    expect(emailText({ ...EMAIL, language: "en" }).startsWith("Subject: ")).toBe(true);
  });

  it("falls back to English for a language nobody added a label for", () => {
    expect(emailText({ ...EMAIL, language: "de" as FollowUpEmail["language"] })).toContain("Subject: ");
  });

  it("omits the label entirely when the draft has no subject", () => {
    expect(emailText({ ...EMAIL, subject: "   " }).startsWith("Bonjour,")).toBe(true);
  });
});

describe("mailtoHref", () => {
  it("opens a draft with no recipient", () => {
    const href = mailtoHref(EMAIL);
    expect(href.startsWith("mailto:?")).toBe(true);

    const parameters = new URLSearchParams(href.slice("mailto:?".length));
    expect(parameters.get("subject")).toBe("Following up on my application");
    expect(parameters.get("body")).toBe(emailBody(EMAIL));
  });
});
