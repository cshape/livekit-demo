'use client';

import type { RemoteParticipant } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import { useParticipantAttribute, useVoiceAssistant } from '@livekit/components-react';
import { cn } from '@/lib/shadcn/utils';

// Mood-ring palette. The agent's set_style tool writes `style.color` as one of
// these keys (picking the one that matches the mood it's performing in); we map
// it to a glow color for the on-screen "mood ring". Classes are spelled out in
// full so Tailwind keeps them in the build.
const RING_COLORS: Record<string, { dot: string; glow: string }> = {
  gray: { dot: 'bg-slate-400', glow: 'shadow-[0_0_12px_2px] shadow-slate-400/60' },
  amber: { dot: 'bg-amber-500', glow: 'shadow-[0_0_12px_2px] shadow-amber-500/60' },
  green: { dot: 'bg-emerald-500', glow: 'shadow-[0_0_12px_2px] shadow-emerald-500/60' },
  blue: { dot: 'bg-blue-500', glow: 'shadow-[0_0_12px_2px] shadow-blue-500/60' },
  violet: { dot: 'bg-violet-500', glow: 'shadow-[0_0_12px_2px] shadow-violet-500/60' },
};

interface MoodIndicatorProps {
  className?: string;
}

export function MoodIndicator({ className }: MoodIndicatorProps) {
  const { agent } = useVoiceAssistant();
  if (!agent) return null;
  return <MoodIndicatorInner agent={agent} className={className} />;
}

function MoodIndicatorInner({
  agent,
  className,
}: {
  agent: RemoteParticipant;
  className?: string;
}) {
  const mode = useParticipantAttribute('style.mode', { participant: agent });
  const mood = useParticipantAttribute('style.mood', { participant: agent });
  const rawColor = useParticipantAttribute('style.color', { participant: agent });

  // Nothing published yet (e.g. mid-connect) — don't render a half-empty pill.
  if (!mode) return null;

  const color = RING_COLORS[rawColor ?? ''] ?? RING_COLORS.green;
  const modeLabel = mode.charAt(0).toUpperCase() + mode.slice(1);
  const label = mood ? `${modeLabel} · ${mood}` : modeLabel;

  return (
    <AnimatePresence mode="popLayout">
      <motion.div
        key={label}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
        className={cn(
          'border-border/60 bg-background/80 text-foreground/80 mx-auto flex w-fit items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium backdrop-blur',
          className
        )}
      >
        <span
          className={cn('size-2 rounded-full transition-colors', color.dot, color.glow)}
          aria-hidden="true"
        />
        <span className="capitalize">{label}</span>
      </motion.div>
    </AnimatePresence>
  );
}
