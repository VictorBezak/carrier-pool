import { Suspense, StrictMode, lazy } from "react";
import { createRoot } from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { LoadBoardPage } from "@/pages/LoadBoardPage";
import { SessionProvider } from "@/session";
import "@/index.css";

const LoadDetailPage = lazy(() => import("@/pages/LoadDetailPage").then((module) => ({ default: module.LoadDetailPage })));

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/loads" replace /> },
      { path: "loads", element: <LoadBoardPage /> },
      {
        path: "loads/:loadId",
        element: (
          <Suspense fallback={<div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">Loading load recommendation</div>}>
            <LoadDetailPage />
          </Suspense>
        )
      },
      { path: "*", element: <Navigate to="/loads" replace /> }
    ]
  }
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SessionProvider>
      <RouterProvider router={router} />
    </SessionProvider>
  </StrictMode>
);
