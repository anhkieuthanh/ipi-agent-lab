import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { AttackPage } from "@/pages/Attack";
import { BatchesPage } from "@/pages/Batches";
import { ConfigPage } from "@/pages/Config";
import { DefensePage } from "@/pages/Defense";
import { LabPage } from "@/pages/Lab";
import { OverviewPage } from "@/pages/Overview";
import { RunDetailPage } from "@/pages/RunDetail";
import { RunsPage } from "@/pages/Runs";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: 1 } },
});

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "batches", element: <BatchesPage /> },
      { path: "attack", element: <AttackPage /> },
      { path: "defense", element: <DefensePage /> },
      { path: "runs", element: <RunsPage /> },
      { path: "runs/:runId", element: <RunDetailPage /> },
      { path: "lab", element: <LabPage /> },
      { path: "config", element: <ConfigPage /> },
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
