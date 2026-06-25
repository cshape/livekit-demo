'use client';

import { useEffect, useMemo, useState } from 'react';
import { RoomEvent, TokenSource } from 'livekit-client';
import { useRoomContext, useSession } from '@livekit/components-react';
import { WarningIcon } from '@phosphor-icons/react/dist/ssr';
import { type AppConfig, CLONE_SELECTION, DEFAULT_VOICE_ID } from '@/app-config';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { ErrorBoundary } from '@/components/app/error-boundary';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/ui/sonner';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { getSandboxTokenSource } from '@/lib/utils';

function AppSetup() {
  useAgentErrors();

  // Log why the room ever disconnects/reconnects, so a "crash mid-convo" shows its
  // client-side reason in the console (network/signal drop vs a client-initiated end).
  const room = useRoomContext();
  useEffect(() => {
    const onDisconnected = (reason?: unknown) =>
      console.warn('[room] disconnected, reason=', reason);
    const onReconnecting = () => console.warn('[room] reconnecting…');
    const onReconnected = () => console.warn('[room] reconnected');
    room.on(RoomEvent.Disconnected, onDisconnected);
    room.on(RoomEvent.Reconnecting, onReconnecting);
    room.on(RoomEvent.Reconnected, onReconnected);
    return () => {
      room.off(RoomEvent.Disconnected, onDisconnected);
      room.off(RoomEvent.Reconnecting, onReconnecting);
      room.off(RoomEvent.Reconnected, onReconnected);
    };
  }, [room]);

  return null;
}

interface AppProps {
  appConfig: AppConfig;
}

export function App({ appConfig }: AppProps) {
  // The voice choice made on the landing page (a preset voice_id or 'clone').
  // It rides agentMetadata to the worker, so it must be in the useSession options
  // before start() runs. Stellan (first preset) is pre-selected.
  const [selection, setSelection] = useState<string>(DEFAULT_VOICE_ID);

  // Recreate the token source whenever the selection changes so it starts with an
  // empty cache. livekit-client's TokenSourceCached has an inverted cache check
  // (shouldReturnCachedValueFromFetch returns the cached token when the fetch
  // options DIFFER from the cached ones), so a single reused source would hand back
  // the stale token minted for the previous selection. A fresh source per selection
  // sidesteps the bug — its cache is empty, so it always fetches with the current
  // agentMetadata.
  const tokenSource = useMemo(() => {
    return typeof process.env.NEXT_PUBLIC_CONN_DETAILS_ENDPOINT === 'string'
      ? getSandboxTokenSource(appConfig)
      : TokenSource.endpoint('/api/token');
    // `selection` is intentionally in the deps (not used in the body) to force a
    // fresh, empty-cache token source whenever the choice changes — see comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appConfig, selection]);

  const sessionOptions = useMemo(
    () => ({
      agentName: appConfig.agentName,
      agentMetadata: JSON.stringify(
        selection === CLONE_SELECTION ? { clone: true } : { voice: selection }
      ),
      // The clone-first flow holds the agent in a pre-conversation "read the script +
      // build the clone" phase before it greets, which sails past the 20s default and
      // would otherwise trip a false "agent did not finish initializing" failure.
      agentConnectTimeoutMilliseconds: 90_000,
    }),
    [appConfig.agentName, selection]
  );

  const session = useSession(tokenSource, sessionOptions);

  return (
    <AgentSessionProvider session={session}>
      <AppSetup />
      <main className="grid h-svh grid-cols-1 place-content-center">
        <ErrorBoundary>
          <ViewController
            appConfig={appConfig}
            selection={selection}
            onSelectionChange={setSelection}
          />
        </ErrorBoundary>
      </main>
      <StartAudioButton label="Start Audio" />
      <Toaster
        icons={{
          warning: <WarningIcon weight="bold" />,
        }}
        position="top-center"
        className="toaster group"
        style={
          {
            '--normal-bg': 'var(--popover)',
            '--normal-text': 'var(--popover-foreground)',
            '--normal-border': 'var(--border)',
          } as React.CSSProperties
        }
      />
    </AgentSessionProvider>
  );
}
