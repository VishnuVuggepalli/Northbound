import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/Button';

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Heading shown in the fallback. */
  title?: string;
  /**
   * When true the recovery action does a full page reload (use at the app root,
   * where in-place reset can't recover a broken shell). When false it resets the
   * boundary in place so the user can retry the page without losing the session.
   */
  fullReload?: boolean;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Catches render/lifecycle errors in its subtree so a single component throw
 * shows a recoverable fallback instead of a blank white screen. React requires
 * error boundaries to be class components.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface for diagnosis — a boundary that swallows silently is worse than
    // the crash. (Replace with a real logger/Sentry sink when one exists.)
    console.error('UI crash caught by ErrorBoundary:', error, info.componentStack);
  }

  private reset = (): void => {
    if (this.props.fullReload) {
      window.location.reload();
    } else {
      this.setState({ error: null });
    }
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div
        role="alert"
        className="flex h-full min-h-[40vh] flex-col items-center justify-center gap-3 px-6 text-center"
      >
        <AlertTriangle className="text-danger" size={28} aria-hidden />
        <div className="text-sm text-fg">
          {this.props.title ?? 'Something went wrong on this page.'}
          <span className="mt-1 block max-w-md text-fg-muted">{error.message}</span>
        </div>
        <Button kind="outline" onClick={this.reset}>
          {this.props.fullReload ? 'Reload' : 'Try again'}
        </Button>
      </div>
    );
  }
}
