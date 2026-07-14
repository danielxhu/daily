"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

/** Catches render errors in the subtree so one broken view doesn't blank the app. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <div
            role="alert"
            className="m-4 rounded border border-bad-fg/30 bg-bad-bg p-4 text-sm text-bad-fg"
          >
            <p className="font-medium">Something went wrong.</p>
            <p className="text-bad-fg">{this.state.error.message}</p>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
