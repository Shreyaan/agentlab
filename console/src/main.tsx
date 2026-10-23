import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router";
import { Shell } from "./components/Shell";
import "./index.css";
import { AuthorPage } from "./pages/Author";
import { EnvironmentEditorPage } from "./pages/EnvironmentEditor";
import { EnvironmentsPage } from "./pages/Environments";
import { ExperimentDetailPage } from "./pages/ExperimentDetail";
import { ExperimentsPage } from "./pages/Experiments";
import { JudgesPage } from "./pages/Judges";
import { NewRunPage } from "./pages/NewRun";
import { ScenarioEditorPage } from "./pages/ScenarioEditor";
import { ScenariosPage } from "./pages/Scenarios";
import { TargetsPage } from "./pages/Targets";
import { TrialDetailPage } from "./pages/TrialDetail";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

// A data router (not <BrowserRouter>) so the scenario editor can block navigation with unsaved changes.
const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { index: true, element: <ExperimentsPage /> },
      { path: "new", element: <NewRunPage /> },
      { path: "experiments/:id", element: <ExperimentDetailPage /> },
      { path: "trials/:id", element: <TrialDetailPage /> },
      { path: "targets", element: <TargetsPage /> },
      { path: "judges", element: <JudgesPage /> },
      { path: "author", element: <AuthorPage /> },
      { path: "environments/new", element: <EnvironmentEditorPage /> },
      { path: "environments/:key/edit", element: <EnvironmentEditorPage /> },
      { path: "environments", element: <EnvironmentsPage /> },
      { path: "environments/:key", element: <EnvironmentsPage /> },
      { path: "scenarios/new", element: <ScenarioEditorPage /> },
      { path: "scenarios/:key/edit", element: <ScenarioEditorPage /> },
      { path: "scenarios", element: <ScenariosPage /> },
      { path: "scenarios/:key", element: <ScenariosPage /> },
      { path: "*", element: <p className="p-6 text-ink2">Page not found.</p> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
