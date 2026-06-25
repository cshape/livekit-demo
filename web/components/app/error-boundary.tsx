'use client';

import React from 'react';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
}

// Contains render crashes in the call view (e.g. the mode toggle / mood pill during a
// rapid switch) so they can't unwind up to the AgentSessionProvider and unmount it,
// which would call room.disconnect() and kill the live call. The room/audio is owned
// above this boundary, so it keeps running while we show a fallback.
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: unknown) {
    console.error('[ErrorBoundary] view crashed; keeping the call connected', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="text-muted-foreground mx-auto max-w-md p-6 text-center text-sm">
            Something glitched on screen, but you&rsquo;re still connected. Refresh if it
            doesn&rsquo;t recover.
          </div>
        )
      );
    }
    return this.props.children;
  }
}
