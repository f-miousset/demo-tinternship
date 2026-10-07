/**
 * The route table, in its own module so a test can mount it.
 *
 * It lives here rather than in `main.tsx` because `main.tsx` calls
 * `createRoot(...)` at import time: anything that imports it starts the real
 * app against the real DOM. Keeping the table separate means the suite mounts
 * *these* routes — the ones production serves — instead of a copy that can
 * drift. See `src/test/routes.test.tsx`.
 */
import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

import { Layout } from "./components/Layout";
import { AccountPage } from "./routes/AccountPage";
import { ApplicationPage } from "./routes/ApplicationPage";
import { JobsPage } from "./routes/JobsPage";
import { RunDetailPage } from "./routes/RunDetailPage";
import { SettingsPage } from "./routes/SettingsPage";
import { TracesPage } from "./routes/TracesPage";
import { TrackerPage } from "./routes/TrackerPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/jobs" replace /> },
      { path: "account", element: <AccountPage /> },
      { path: "jobs", element: <JobsPage /> },
      { path: "applications/:applicationId", element: <ApplicationPage /> },
      { path: "tracker", element: <TrackerPage /> },
      { path: "traces", element: <TracesPage /> },
      { path: "traces/:runId", element: <RunDetailPage /> },
      { path: "settings", element: <SettingsPage /> },
      // Profile, Interview and Strategy were steps 1–3, each on its own route.
      // They are configured once, so they are sections of one Account page now
      // — these keep old bookmarks and history entries working.
      { path: "profile", element: <Navigate to="/account" replace /> },
      { path: "interview", element: <Navigate to="/account" replace /> },
      { path: "strategy", element: <Navigate to="/account" replace /> },
    ],
  },
];

/** The defaults every screen's queries inherit. Shared with the test harness. */
export const QUERY_DEFAULTS = { queries: { retry: 1, refetchOnWindowFocus: false } };
