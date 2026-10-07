/** Putting a generated document on the candidate's disk without being asked.
 *
 * A run ends with the file they came for, and the next thing they do with it is
 * always the same: download it, open it, attach it to a form. The Download
 * .docx link on the artifact's tab is still there and still the way back to an
 * older version — this is the step it saved them from having to remember.
 */

/** The export URL for one artifact. The same one the tab's link points at. */
export function exportUrl(artifactId: number): string {
  return `/api/applications/artifacts/${artifactId}/export`;
}

/** Ask the browser to save one artifact's `.docx`.
 *
 * `download=""` rather than a filename: the response carries
 * `Content-Disposition: attachment; filename=Resume_…docx`, assembled from the
 * candidate's name, the employer and the role, and for a same-origin response
 * that header wins over the attribute. Naming the file here would mean building
 * that string twice, in two languages, in a place that has neither row.
 */
export function downloadArtifact(artifactId: number): void {
  const link = document.createElement("a");
  link.href = exportUrl(artifactId);
  link.download = "";
  link.rel = "noreferrer";
  // Appended rather than clicked detached: Firefox ignores a click on an
  // element that is not in the document.
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/** The order the documents are saved in, which is the order they are read in. */
const DOCUMENT_KINDS = ["resume", "cover_letter"] as const;

/**
 * Save every document a run produced, oldest kind first.
 *
 * Staggered, because a browser asked for two files in the same tick treats the
 * second as an unsolicited download and drops it — Chrome shows one permission
 * prompt for the pair and Safari keeps only the first. A fifth of a second is
 * under the threshold nobody notices and over the one that loses a file.
 *
 * Kinds that are not documents are skipped rather than trusted to 404: the
 * interview brief and the contact shortlist are read in the app and have no
 * `.docx` at all, and a run that grows a third artifact should not start
 * downloading it by default.
 */
export async function downloadDocuments(
  artifacts: Record<string, { id: number }> | null | undefined,
  gap = 200,
): Promise<void> {
  const ids = DOCUMENT_KINDS.map((kind) => artifacts?.[kind]?.id).filter(
    (id): id is number => typeof id === "number",
  );
  for (const [index, id] of ids.entries()) {
    if (index > 0) await new Promise((resolve) => setTimeout(resolve, gap));
    downloadArtifact(id);
  }
}
