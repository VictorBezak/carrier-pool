import { Link, Outlet } from "react-router-dom";
import { Clock3, Eye, TriangleAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { TooltipProvider } from "@/components/ui/tooltip";
import { DevSheet } from "@/components/DevSheet";
import { timestamp } from "@/format";
import { useSession } from "@/session";

export function AppShell() {
  const session = useSession();

  return (
    <TooltipProvider>
      <div className="flex min-h-screen flex-col">
        <header className="sticky top-0 z-40 flex h-12 shrink-0 items-center gap-3 border-b bg-card px-4">
          <Link to="/loads" className="flex items-center gap-2.5">
            <span className="grid size-5 place-items-center rounded-sm bg-primary font-mono text-[10px] font-semibold text-primary-foreground">
              CP
            </span>
            <span className="font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">Carrier Pool</span>
          </Link>
          <Separator orientation="vertical" className="h-4" />
          <span className="truncate text-[13px] font-medium">{session.broker?.name ?? "Loading"}</span>

          <div className="ml-auto flex items-center gap-2">
            {session.asOf && (
              <Badge variant="outline" className="border-dev/40 bg-dev-surface text-dev-foreground">
                <Clock3 />
                As of {timestamp(session.asOf)}
              </Badge>
            )}
            {session.impersonating && (
              <Badge variant="outline" className="border-dev/40 bg-dev-surface text-dev-foreground">
                <Eye />
                Viewing as {session.broker?.name}
              </Badge>
            )}
            <DevSheet />
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1680px] flex-1 px-4 py-5">
          {session.error ? (
            <Alert variant="destructive">
              <TriangleAlert />
              <AlertTitle>Could not load broker data</AlertTitle>
              <AlertDescription>{session.error}</AlertDescription>
            </Alert>
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </TooltipProvider>
  );
}
