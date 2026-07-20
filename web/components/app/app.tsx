'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useSession } from '@livekit/components-react';
import { WarningIcon } from '@phosphor-icons/react/dist/ssr';
import {
  type AppConfig,
  CLONE_SELECTION,
  DESIGN_INSTRUCTION_MAX_CHARS,
  DESIGN_SELECTION,
  getDefaultVoiceId,
} from '@/app-config';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { AppHeader } from '@/components/app/app-header';
import { ErrorBoundary } from '@/components/app/error-boundary';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/ui/sonner';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { type Locale, LocaleProvider, UI_STRINGS } from '@/lib/i18n';
import { clearTokenCache, createCachingTokenSource } from '@/lib/token-source';
import { getSandboxTokenSource } from '@/lib/utils';

function AppSetup() {
  useAgentErrors();

  return null;
}

interface AppProps {
  appConfig: AppConfig;
  /** Page locale: 'en' on /, 'ja' on /jp. Drives UI strings, the preset voice
   * list, and the `lang` the agent worker localizes its side against. */
  locale?: Locale;
  /** When set, a branded header (logo + this title) is shown during the in-call
   * cloning workflow (not the welcome screen). Used by /cloning. */
  headerTitle?: string;
  /** Landing-page selection to preselect instead of the locale's first preset
   * (e.g. CLONE_SELECTION on /cloning). */
  initialSelection?: string;
}

export function App({ appConfig, locale = 'en', headerTitle, initialSelection }: AppProps) {
  // The voice choice made on the landing page (a preset voice_id, 'clone', or
  // 'design'). It rides agentMetadata to the worker, so it must be in the
  // useSession options before start() runs. The locale's first preset is
  // pre-selected (Maren on /, さとる on /jp).
  const [selection, setSelection] = useState<string>(
    () => initialSelection ?? getDefaultVoiceId(locale)
  );
  // Free-text description for the "design a voice" option; rides agentMetadata too.
  const [designInstruction, setDesignInstruction] = useState('');

  const agentMetadata = useMemo(() => {
    if (selection === CLONE_SELECTION) return JSON.stringify({ clone: true, lang: locale });
    if (selection === DESIGN_SELECTION) {
      return JSON.stringify({
        design: designInstruction.trim().slice(0, DESIGN_INSTRUCTION_MAX_CHARS),
        lang: locale,
      });
    }
    return JSON.stringify({ voice: selection, lang: locale });
  }, [selection, designInstruction, locale]);

  // Recreate the token source whenever the metadata changes so it starts with an
  // empty cache. livekit-client's TokenSourceCached has an inverted cache check
  // (shouldReturnCachedValueFromFetch returns the cached token when the fetch
  // options DIFFER from the cached ones), so a single reused source would hand back
  // the stale token minted for the previous selection. A fresh source per metadata
  // value sidesteps the bug — its cache is empty, so it always fetches with the
  // current agentMetadata. Actual token reuse (so the landing-page prefetch isn't
  // wasted) lives in createCachingTokenSource's module-level cache instead.
  const tokenSource = useMemo(() => {
    return typeof process.env.NEXT_PUBLIC_CONN_DETAILS_ENDPOINT === 'string'
      ? getSandboxTokenSource(appConfig)
      : createCachingTokenSource();
    // `agentMetadata` is intentionally in the deps (not used in the body) to force a
    // fresh, empty-cache token source whenever it changes — see comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appConfig, agentMetadata]);

  const sessionOptions = useMemo(
    () => ({
      agentName: appConfig.agentName,
      agentMetadata,
      // The clone/design-first flows hold the agent in a pre-conversation setup
      // phase before it greets, which sails past the 20s default and would
      // otherwise trip a false "agent did not finish initializing" failure.
      agentConnectTimeoutMilliseconds: 90_000,
    }),
    [appConfig.agentName, agentMetadata]
  );

  const session = useSession(tokenSource, sessionOptions);

  // --- Prewarm ---------------------------------------------------------------
  // Everything below shaves time off the moment the user clicks "Start call";
  // none of it is required for correctness.

  const sessionRef = useRef(session);
  sessionRef.current = session;

  // Warm the microphone on page load: surfacing the permission prompt (and doing
  // the device open once) now means start() publishes audio immediately instead of
  // blocking on the prompt + device init. Tracks are stopped right away so the
  // mic indicator doesn't stay lit while the user is still on the landing page.
  useEffect(() => {
    navigator.mediaDevices
      ?.getUserMedia({ audio: true })
      .then((stream) => stream.getTracks().forEach((track) => track.stop()))
      .catch(() => {
        // Denied or unavailable — start() will ask again; nothing to do here.
      });
  }, []);

  // Prefetch a token and warm the signal path (DNS, TLS, LiveKit Cloud region
  // pinning) on load and again whenever the voice selection changes. The minted
  // token lands in the module-level cache, so start() reuses it instead of paying
  // the /api/token round trip. Keyed on `selection` (not the full metadata) so
  // typing a design description doesn't re-mint per keystroke.
  useEffect(() => {
    const current = sessionRef.current;
    if (current.isConnected) return;
    current.prepareConnection?.().catch(() => {
      // Best-effort: a failed prewarm just means start() does the work instead.
    });
  }, [selection]);

  // A consumed token pins a room name whose agent job may still be shutting down
  // after the call — never reuse it. Dropping the cache on connect means the next
  // call mints fresh.
  useEffect(() => {
    if (session.isConnected) clearTokenCache();
  }, [session.isConnected]);

  return (
    <LocaleProvider locale={locale}>
      <AgentSessionProvider session={session}>
        <AppSetup />
        {/* Branded header only during the cloning workflow (the in-call
            conversation), not on the welcome/selection screen. It's a fixed
            overlay above the in-call view (which is fixed inset-0). */}
        {headerTitle && session.isConnected && <AppHeader title={headerTitle} />}
        <main className="grid h-svh grid-cols-1 place-content-center">
          <ErrorBoundary>
            <ViewController
              appConfig={appConfig}
              selection={selection}
              onSelectionChange={setSelection}
              designInstruction={designInstruction}
              onDesignInstructionChange={setDesignInstruction}
            />
          </ErrorBoundary>
        </main>
        <StartAudioButton label={UI_STRINGS[locale].startAudio} />
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
    </LocaleProvider>
  );
}
