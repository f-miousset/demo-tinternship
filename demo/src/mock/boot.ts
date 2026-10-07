/**
 * Installs the mock as a side effect of being imported.
 *
 * Its own module so that `main.demo.tsx` can import it *before* the app with
 * plain static imports: ES modules are evaluated in import order, so `fetch`
 * is replaced before a line of the app runs. A dynamic `import()` of the app
 * would also run it later — too late: the app registers its service worker on
 * the window's `load` event, which had already fired, and the demo shipped
 * without one (documentation/gotchas.md).
 */
import { installMock } from "./install";

installMock();
