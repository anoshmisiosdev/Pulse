import { Component, type ReactNode } from "react";

/** Catches render errors so a component bug degrades to a card, not a white screen. */
export default class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("Unhandled render error:", error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="grid min-h-[60vh] place-items-center text-center">
        <div className="glass max-w-md p-8">
          <p className="font-display text-lg font-semibold" style={{ color: "var(--ink)" }}>
            Something went wrong
          </p>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            The page hit an unexpected error. Reloading usually fixes it.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 rounded-full px-5 py-2 text-sm font-semibold text-white"
            style={{ background: "var(--accent)" }}
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
