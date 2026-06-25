'use client';

import type { RemoteParticipant } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import {
  type AgentState,
  useParticipantAttribute,
  useVoiceAssistant,
} from '@livekit/components-react';
import { cn } from '@/lib/shadcn/utils';

// Mood-ring palette. A separate, cosmetic LLM in the agent process reads each line
// the agent speaks, classifies the emotion it conveys, and writes `style.mood` (a
// one-word feeling) + `style.color` (one of these keys). It never touches the agent's
// delivery — it just drives this ring. Classes are spelled out in full so Tailwind
// keeps them in the build.
const RING_COLORS: Record<string, { dot: string; glow: string }> = {
  gray: { dot: 'bg-slate-400', glow: 'shadow-[0_0_12px_2px] shadow-slate-400/60' },
  amber: { dot: 'bg-amber-500', glow: 'shadow-[0_0_12px_2px] shadow-amber-500/60' },
  green: { dot: 'bg-emerald-500', glow: 'shadow-[0_0_12px_2px] shadow-emerald-500/60' },
  blue: { dot: 'bg-blue-500', glow: 'shadow-[0_0_12px_2px] shadow-blue-500/60' },
  violet: { dot: 'bg-violet-500', glow: 'shadow-[0_0_12px_2px] shadow-violet-500/60' },
};

// Live pipeline state → a short human label shown as grey subtext next to the mood.
// `listening` is the window the user is speaking (until the agent flips to `thinking`).
const STATE_LABEL: Partial<Record<AgentState, string>> = {
  listening: 'listening',
  thinking: 'thinking',
  speaking: 'speaking',
  initializing: 'connecting',
  connecting: 'connecting',
};

interface MoodIndicatorProps {
  className?: string;
}

export function MoodIndicator({ className }: MoodIndicatorProps) {
  const { agent, state } = useVoiceAssistant();
  if (!agent) return null;
  return <MoodIndicatorInner agent={agent} state={state} className={className} />;
}

function MoodIndicatorInner({
  agent,
  state,
  className,
}: {
  agent: RemoteParticipant;
  state: AgentState;
  className?: string;
}) {
  const mood = useParticipantAttribute('style.mood', { participant: agent });
  const rawColor = useParticipantAttribute('style.color', { participant: agent });

  const moodLabel = mood ? mood.charAt(0).toUpperCase() + mood.slice(1) : null;

  // `failed` means the agent participant briefly dropped from the room (see
  // useAgentErrors — we no longer end the call on this). Surface it as a calm,
  // transient "Reconnecting…" state on an amber dot instead of a frozen mood pill.
  const reconnecting = state === 'failed';
  const color = reconnecting
    ? RING_COLORS.amber
    : (RING_COLORS[rawColor ?? ''] ?? RING_COLORS.green);

  // Otherwise the mood is always the primary label once we have one (e.g. "Curious");
  // the live pipeline state rides along as grey subtext ("Curious · listening" /
  // "· speaking" / "· thinking"). Before any mood lands, fall back to the state word.
  const stateLabel = STATE_LABEL[state];
  const primary = reconnecting
    ? 'Reconnecting…'
    : (moodLabel ?? (stateLabel ? stateLabel[0].toUpperCase() + stateLabel.slice(1) : 'Listening'));
  const suffix = reconnecting ? null : moodLabel && stateLabel ? stateLabel : null;

  // Pulse while actively engaged. Listening gets a softer, slower pulse than the
  // thinking/speaking beat so the two read differently at a glance.
  const isListening = state === 'listening';
  const pulse = reconnecting || isListening || state === 'speaking' || state === 'thinking';
  const pulseScale = isListening ? [1, 1.2, 1] : [1, 1.35, 1];
  const pulseOpacity = isListening ? [0.9, 0.5, 0.9] : [1, 0.7, 1];
  const pulseDuration = isListening ? 1.6 : 1.1;

  return (
    <AnimatePresence mode="popLayout">
      <motion.div
        key={`${primary}-${suffix ?? ''}`}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
        className={cn(
          'border-border/60 bg-background/80 text-foreground/80 mx-auto flex w-fit items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium backdrop-blur',
          className
        )}
      >
        <motion.span
          className={cn('size-2 shrink-0 rounded-full', color.dot, color.glow)}
          animate={pulse ? { scale: pulseScale, opacity: pulseOpacity } : { scale: 1, opacity: 1 }}
          transition={
            pulse
              ? { duration: pulseDuration, repeat: Infinity, ease: 'easeInOut' }
              : { duration: 0.2 }
          }
          aria-hidden="true"
        />
        <span>{primary}</span>
        {suffix && <span className="text-foreground/40">· {suffix}</span>}
      </motion.div>
    </AnimatePresence>
  );
}
