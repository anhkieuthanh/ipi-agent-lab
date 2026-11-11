import "./index.css";

import { Provider as TooltipProvider } from "@radix-ui/react-tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ComponentType, lazy, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { Layout } from "@/components/Layout";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: true, retry: 1 } },
});

/** Mỗi trang một gói riêng — chỉ tải khi mở. */
function page<K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) {
  return lazy(() => load().then((m) => ({ default: m[name] })));
}

const Overview = page(() => import("@/pages/Overview"), "OverviewPage");
const System = page(() => import("@/pages/System"), "SystemPage");
const Batches = page(() => import("@/pages/Batches"), "BatchesPage");
const Attack = page(() => import("@/pages/Attack"), "AttackPage");
const Defense = page(() => import("@/pages/Defense"), "DefensePage");
const Runs = page(() => import("@/pages/Runs"), "RunsPage");
const RunDetail = page(() => import("@/pages/RunDetail"), "RunDetailPage");
const Lab = page(() => import("@/pages/Lab"), "LabPage");
const Config = page(() => import("@/pages/Config"), "ConfigPage");
const Process = page(() => import("@/pages/Process"), "ProcessPage");

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Overview /> },
      { path: "system", element: <System /> },
      { path: "batches", element: <Batches /> },
      { path: "attack", element: <Attack /> },
      { path: "defense", element: <Defense /> },
      { path: "runs", element: <Runs /> },
      { path: "runs/:runId", element: <RunDetail /> },
      { path: "lab", element: <Lab /> },
      { path: "config", element: <Config /> },
      { path: "process", element: <Process /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={250} skipDelayDuration={300}>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
