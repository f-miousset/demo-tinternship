/**
 * Saving what a run produced, without being asked.
 *
 * The rules worth pinning are the ones a browser enforces silently: two
 * downloads in the same tick lose one, an anchor that is not in the document
 * never fires in Firefox, and anything that is not a `.docx` has no export at
 * all. Each of those fails as *a missing file*, which is the hardest kind of
 * bug to notice in something that runs for two minutes and ends in a save
 * dialog.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadArtifact, downloadDocuments, exportUrl } from "./download";

/** Every anchor click, in order, as the browser would have seen it. */
function recordClicks(): { href: string; download: string | null; mounted: boolean }[] {
  const clicks: { href: string; download: string | null; mounted: boolean }[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicks.push({
      href: this.getAttribute("href") ?? "",
      download: this.getAttribute("download"),
      // Firefox ignores a click on an element that is not in the document.
      mounted: this.isConnected,
    });
  });
  return clicks;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("downloading a generated document", () => {
  it("asks for the artifact's own export URL", () => {
    const clicks = recordClicks();

    downloadArtifact(7);

    expect(clicks).toEqual([{ href: exportUrl(7), download: "", mounted: true }]);
  });

  it("leaves no anchor behind in the document", () => {
    recordClicks();

    downloadArtifact(7);

    expect(document.querySelectorAll("a[download]").length).toBe(0);
  });

  it("names nothing, so the response's own filename wins", () => {
    // `Content-Disposition` carries `Resume_Alex_Martin_Acme_….docx`,
    // assembled from three rows the browser does not have. An empty `download`
    // is what lets that header name the file.
    const clicks = recordClicks();

    downloadArtifact(7);

    expect(clicks[0].download).toBe("");
  });

  it("saves both documents, résumé first, staggered", async () => {
    const clicks = recordClicks();

    await downloadDocuments({ resume: { id: 3 }, cover_letter: { id: 4 } }, 0);

    expect(clicks.map((click) => click.href)).toEqual([exportUrl(3), exportUrl(4)]);
  });

  it("waits between them, because a browser drops the second otherwise", async () => {
    const clicks = recordClicks();
    vi.useFakeTimers();

    const done = downloadDocuments({ resume: { id: 3 }, cover_letter: { id: 4 } }, 200);
    await vi.advanceTimersByTimeAsync(0);
    expect(clicks.length).toBe(1);

    await vi.advanceTimersByTimeAsync(200);
    await done;
    expect(clicks.length).toBe(2);
  });

  it("saves only what the run produced", async () => {
    const clicks = recordClicks();

    await downloadDocuments({ cover_letter: { id: 9 } }, 0);

    expect(clicks.map((click) => click.href)).toEqual([exportUrl(9)]);
  });

  it("ignores artifacts that are not documents", async () => {
    // The brief and the shortlist are read in the app and have no .docx at all.
    const clicks = recordClicks();

    await downloadDocuments({ interview_prep: { id: 11 }, contacts: { id: 12 } }, 0);

    expect(clicks).toEqual([]);
  });

  it("does nothing at all for a run that saved nothing", async () => {
    const clicks = recordClicks();

    await downloadDocuments(undefined, 0);
    await downloadDocuments({}, 0);

    expect(clicks).toEqual([]);
  });
});
