/**
 * Error boundary.
 *
 * Without one, a render-time exception anywhere unmounts the whole tree and the
 * user is left staring at a blank white page with no way forward.
 */
import { Component } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { Button } from "../ui/index.jsx";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Left as console output on purpose: wiring this to a real error-reporting
    // service (Sentry et al.) is a deployment decision, not an app decision.
    console.error("Unhandled UI error:", error, info?.componentStack);
  }

  handleReset = () => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div role="alert" className="flex min-h-[60vh] flex-col items-center justify-center px-6 text-center">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-danger-soft">
          <AlertTriangle size={22} className="text-danger" aria-hidden="true" />
        </div>
        <h1 className="text-xl font-semibold text-ink">This view failed to load</h1>
        <p className="mt-1.5 max-w-md text-base text-muted">
          An unexpected error broke this page. The rest of the app is unaffected - you can retry, or
          go back to the overview.
        </p>

        {import.meta.env.DEV && (
          <pre className="mt-4 max-w-xl overflow-auto rounded-md border border-line bg-canvas p-3 text-left text-xs text-danger">
            {error.message}
          </pre>
        )}

        <div className="mt-5 flex gap-2">
          <Button icon={RefreshCw} onClick={this.handleReset}>Try again</Button>
          <Button variant="secondary" onClick={() => { window.location.href = "/"; }}>
            Back to overview
          </Button>
        </div>
      </div>
    );
  }
}
