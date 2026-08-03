import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { LoadBoardPage } from "@/pages/LoadBoardPage";
import { LoadDetailPage } from "@/pages/LoadDetailPage";
import { SessionProvider } from "@/session";
import "@/index.css";

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/loads" replace /> },
      { path: "loads", element: <LoadBoardPage /> },
      { path: "loads/:loadId", element: <LoadDetailPage /> },
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
