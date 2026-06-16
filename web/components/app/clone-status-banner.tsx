'use client';

import { useEffect, useState } from 'react';
import type { RemoteParticipant } from 'livekit-client';
import { useParticipantAttribute, useVoiceAssistant } from '@livekit/components-react';
import { AnimatePresence, motion } from 'motion/react';
import { cn } from '@/lib/shadcn/utils';

const RECORDING_DURATION_SECS = 15;

type CloneState = 'idle' | 'recording' | 'cloning' | 'ready' | 'playing';

const PILL_META: Partial<
  Record<CloneState, { label: string; tone: string; spinner?: boolean }>
> = {
  cloning: {
    label: 'Cloning your voice…',
    tone: 'bg-blue-500/10 text-blue-200 ring-blue-500/40',
    spinner: true,
  },
  ready: {
    label: 'Your cloned voice is ready',
    tone: 'bg-emerald-500/10 text-emerald-200 ring-emerald-500/40',
  },
  playing: {
    label: 'Speaking in your cloned voice',
    tone: 'bg-purple-500/10 text-purple-200 ring-purple-500/40',
  },
};

export function CloneStatusBanner() {
  // useParticipantAttribute asserts a non-null participant, so we can only call it
  // once the agent participant is connected. Gate via a wrapper.
  const { agent } = useVoiceAssistant();
  if (!agent) return null;
  return <CloneStatusBannerInner agent={agent} />;
}

function CloneStatusBannerInner({ agent }: { agent: RemoteParticipant }) {
  const raw = useParticipantAttribute('clone.state', { participant: agent });
  const state = (raw as CloneState | undefined) ?? 'idle';
  const pill = state !== 'recording' ? PILL_META[state] : undefined;

  return (
    <>
      <AnimatePresence>
        {state === 'recording' && <RecordingOverlay key="recording-overlay" />}
      </AnimatePresence>
      <AnimatePresence>
        {pill && (
          <motion.div
            key={state}
            initial={{ opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
            className="fixed top-6 left-1/2 z-50 -translate-x-1/2"
          >
            <div
              className={cn(
                'flex items-center gap-2.5 rounded-full px-4 py-2 text-sm font-medium ring-1 backdrop-blur',
                pill.tone
              )}
            >
              {pill.spinner && (
                <span
                  className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
                  aria-hidden
                />
              )}
              {pill.label}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

function RecordingOverlay() {
  const [secondsLeft, setSecondsLeft] = useState(RECORDING_DURATION_SECS);

  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => {
      const elapsed = (Date.now() - start) / 1000;
      const remaining = Math.max(0, Math.ceil(RECORDING_DURATION_SECS - elapsed));
      setSecondsLeft(remaining);
      if (remaining <= 0) {
        clearInterval(id);
      }
    }, 250);
    return () => clearInterval(id);
  }, []);

  const radius = 70;
  const stroke = 8;
  const size = (radius + stroke) * 2;
  const circumference = 2 * Math.PI * radius;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.92 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center"
    >
      <div className="bg-background/70 flex flex-col items-center gap-7 rounded-3xl px-12 py-10 shadow-2xl ring-1 ring-red-500/40 backdrop-blur-xl">
        <div className="relative" style={{ width: size, height: size }}>
          <svg width={size} height={size} className="-rotate-90">
            <circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              strokeWidth={stroke}
              className="stroke-red-500/15"
            />
            {/* GPU-driven CSS animation — one animation, no per-frame React renders. */}
            <circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={circumference}
              className="stroke-red-400 [animation:clone-countdown_15s_linear_forwards]"
              style={
                {
                  '--circumference': `${circumference}`,
                } as React.CSSProperties
              }
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-5xl font-semibold tabular-nums text-red-200">
              {secondsLeft}
            </span>
          </div>
        </div>
        <div className="text-center">
          <div className="flex items-center justify-center gap-2 text-lg font-semibold text-red-200">
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-current" />
            </span>
            Recording your voice
          </div>
          <div className="text-muted-foreground mt-1.5 text-sm">
            Just talk about anything — I&apos;ll holler when I&apos;ve got enough.
          </div>
        </div>
      </div>
      <style>{`
        @keyframes clone-countdown {
          from { stroke-dashoffset: 0; }
          to   { stroke-dashoffset: var(--circumference); }
        }
      `}</style>
    </motion.div>
  );
}
