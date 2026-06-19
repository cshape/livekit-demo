'use client';

import { useEffect, useRef } from 'react';
import type { RemoteParticipant } from 'livekit-client';
import { XIcon } from 'lucide-react';
import {
  useParticipantAttribute,
  useSessionContext,
  useSessionMessages,
  useVoiceAssistant,
} from '@livekit/components-react';
import { clearDebugLogs, pushDebugLog, setDebugEnabled, useDebugState } from '@/lib/debug-store';
import { cn } from '@/lib/shadcn/utils';

function ts(t: number): string {
  const d = new Date(t);
  return (
    d.toLocaleTimeString('en-US', { hour12: false }) +
    '.' +
    String(d.getMilliseconds()).padStart(3, '0')
  );
}

const SOURCE_TONE: Record<string, string> = {
  livekit: 'text-sky-400',
  clone: 'text-emerald-400',
  system: 'text-amber-400',
};

/**
 * Logs `clone.*` participant-attribute transitions into the debug buffer so the
 * overlay shows what the agent is doing (cloning → ready → playing), not just
 * raw LiveKit chatter. Self-gating: renders nothing, only present to run hooks.
 */
function CloneStateLogger() {
  const { agent } = useVoiceAssistant();
  if (!agent) return null;
  return <CloneStateLoggerInner agent={agent} />;
}

function CloneStateLoggerInner({ agent }: { agent: RemoteParticipant }) {
  const state = useParticipantAttribute('clone.state', { participant: agent });
  const captureSecs = useParticipantAttribute('clone.capture_secs', { participant: agent });
  const lastState = useRef<string | undefined>(undefined);
  const lastSecs = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (state && state !== lastState.current) {
      lastState.current = state;
      pushDebugLog({ level: 'info', source: 'clone', message: `clone.state → ${state}` });
    }
  }, [state]);

  useEffect(() => {
    if (captureSecs && captureSecs !== lastSecs.current) {
      lastSecs.current = captureSecs;
      pushDebugLog({
        level: 'info',
        source: 'clone',
        message: `clone.capture_secs → ${captureSecs}s`,
      });
    }
  }, [captureSecs]);

  return null;
}

/**
 * Hidden debug overlay revealed by typing `/debug` in the chat. Shows the raw
 * agent transcript (with the `[emotion]`/`[break]` markers the normal transcript
 * strips) and a live tail of LiveKit client logs + clone-state transitions.
 */
export function DebugPanel() {
  const { enabled, logs } = useDebugState();
  const session = useSessionContext();
  const { messages } = useSessionMessages(session);
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: 'end' });
  }, [logs, enabled]);

  if (!enabled) return <CloneStateLogger />;

  return (
    <>
      <CloneStateLogger />
      <div className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-md flex-col border-l border-white/10 bg-zinc-950/95 font-mono text-[11px] text-zinc-300 shadow-2xl backdrop-blur">
        <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            <span className="font-semibold tracking-wide text-zinc-100">DEBUG</span>
            <span className="text-zinc-500">/debug to toggle</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={clearDebugLogs}
              className="rounded px-2 py-1 text-zinc-400 hover:bg-white/10 hover:text-zinc-100"
            >
              clear
            </button>
            <button
              type="button"
              aria-label="Close debug panel"
              onClick={() => setDebugEnabled(false)}
              className="rounded p-1 text-zinc-400 hover:bg-white/10 hover:text-zinc-100"
            >
              <XIcon className="size-4" />
            </button>
          </div>
        </div>

        {/* Raw transcript — includes the bracket markers the chat UI hides. */}
        <div className="flex max-h-[45%] flex-col border-b border-white/10">
          <div className="px-3 py-1.5 text-[10px] font-semibold tracking-widest text-zinc-500 uppercase">
            Transcript (raw LLM output)
          </div>
          <div className="flex-1 space-y-1.5 overflow-y-auto px-3 pb-2 [scrollbar-width:thin]">
            {messages.length === 0 ? (
              <div className="text-zinc-600">No messages yet.</div>
            ) : (
              messages.map((m) => (
                <div key={m.id} className="whitespace-pre-wrap">
                  <span className={m.from?.isLocal ? 'text-zinc-500' : 'text-fuchsia-400'}>
                    {m.from?.isLocal ? 'user' : 'agent'}
                  </span>{' '}
                  <span className="text-zinc-300">{highlightTags(m.message)}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* LiveKit client logs + clone-state transitions. */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="px-3 py-1.5 text-[10px] font-semibold tracking-widest text-zinc-500 uppercase">
            LiveKit logs
          </div>
          <div className="flex-1 space-y-0.5 overflow-y-auto px-3 pb-3 [scrollbar-width:thin]">
            {logs.length === 0 ? (
              <div className="text-zinc-600">No logs yet.</div>
            ) : (
              logs.map((l) => (
                <div key={l.id} className="flex gap-2 whitespace-pre-wrap">
                  <span className="shrink-0 text-zinc-600">{ts(l.ts)}</span>
                  <span
                    className={cn('shrink-0 uppercase', SOURCE_TONE[l.source] ?? 'text-zinc-400')}
                  >
                    {l.source}
                  </span>
                  <span className="break-all text-zinc-400">{l.message}</span>
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </div>
      </div>
    </>
  );
}

// Render bracket markers ([excited], [break], …) in a distinct color so it's
// obvious what the LLM emitted vs. what gets spoken.
function highlightTags(text: string) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return parts.map((part, i) =>
    /^\[[^\]]+\]$/.test(part) ? (
      <span key={i} className="text-yellow-400">
        {part}
      </span>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}
