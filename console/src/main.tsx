import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router";
import { Shell } from "./components/Shell";
import "./index.css";
import { ExperimentDetailPage } from "./pages/ExperimentDetail";
import { ExperimentsPage } from "./pages/Experiments";
import { NewRunPage } from "./pages/NewRun";
import { ScenariosPage } from "./pages/Scenarios";
import { TargetsPage } from "./pages/Targets";
import { TrialDetailPage } from "./pages/TrialDetail";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<ExperimentsPage />} />
            <Route path="new" element={<NewRunPage />} />
            <Route path="experiments/:id" element={<ExperimentDetailPage />} />
            <Route path="trials/:id" element={<TrialDetailPage />} />
            <Route path="targets" element={<TargetsPage />} />
            <Route path="scenarios" element={<ScenariosPage />} />
            <Route path="scenarios/:key" element={<ScenariosPage />} />
            <Route path="*" element={<p className="p-6 text-ink2">Page not found.</p>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
