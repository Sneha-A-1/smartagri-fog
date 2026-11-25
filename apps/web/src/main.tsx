import "@fontsource-variable/instrument-sans";
import "./index.css";
import "./i18n";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Link, RouterProvider } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { MODULES } from "./modules/registry";
import { PlannedPage } from "./pages/PlannedPage";
import { applyTheme, useUi } from "./stores/ui";

applyTheme(useUi.getState().theme);

const JobDetail = lazy(() => import("./pages/JobDetail"));
const PluginDetail = lazy(() => import("./pages/PluginDetail"));

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000, retry: 1 } } });

const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      ...MODULES.map((m) => {
        const Page = m.component;
        return { path: m.path, element: Page ? <Page /> : <PlannedPage module={m} /> };
      }),
      { path: "/algorithms/:pluginId", element: <PluginDetail /> },
      { path: "/jobs/:jobId", element: <JobDetail /> },
      {
        path: "*",
        element: (
          <p className="text-ink-2">
            This page doesn't exist. <Link className="text-accent hover:underline" to="/">Go to the overview</Link>
          </p>
        ),
      },
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
