export function SiteFooter() {
    return (
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col gap-1 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:justify-between">
          <p>
            Data:{" "}
            <a
              href="https://psi.nasa.gov"
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-4 hover:text-foreground"
            >
              NASA Physical Sciences Informatics
            </a>{" "}
            (CC0). Each finding cites its PSI investigation and DOI.
          </p>
          <p>Built for NASA Space Apps 2026 · Flame in Freefall</p>
        </div>
      </footer>
    );
  }