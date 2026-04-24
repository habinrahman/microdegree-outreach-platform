import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

type Props = { children: ReactNode };
type State = { error: Error | null };

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[RouteErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <Alert variant="destructive" className="rounded-xl border shadow-sm">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle className="text-lg font-semibold">This view hit an error</AlertTitle>
          <AlertDescription className="space-y-3 text-sm text-gray-500">
            <p className="font-mono text-xs text-foreground/90">{this.state.error.message}</p>
            <Button type="button" size="sm" variant="outline" onClick={() => this.setState({ error: null })}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      );
    }
    return this.props.children;
  }
}
