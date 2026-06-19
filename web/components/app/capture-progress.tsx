'use client';

import type { RemoteParticipant } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import { useParticipantAttribute, useVoiceAssistant } from '@livekit/components-react';
import { cn } from '@/lib/shadcn/utils';

const CAPTURE_THRESHOLD_SECS = 10;

type CloneState = 'idle' | 'cloning' | 'ready' | 'playing';

interface CaptureProgressProps {
  className?: string;
}

export function CaptureProgress({ className }: CaptureProgressProps) {
  const { agent } = useVoiceAssistant();
  if (!agent) return null;
  return <CaptureProgressInner agent={agent} className={className} />;
}

function CaptureProgressInner({
  agent,
  className,
}: {
  agent: RemoteParticipant;
  className?: string;
}) {
  const rawSecs = useParticipantAttribute('clone.capture_secs', { participant: agent });
  const rawState = useParticipantAttribute('clone.state', { participant: agent });
  const state = (rawState as CloneState | undefined) ?? 'idle';

  // Once the clone pipeline takes over (state leaves 'idle'), capture is done —
  // hide this bar.
  if (state !== 'idle') return null;

  const secs = Number.isFinite(Number(rawSecs)) ? Number(rawSecs) : 0;
  const clamped = Math.min(secs, CAPTURE_THRESHOLD_SECS);
  const pct = (clamped / CAPTURE_THRESHOLD_SECS) * 100;
  const ready = secs >= CAPTURE_THRESHOLD_SECS;

  return (
    <AnimatePresence>
      <motion.div
        key="capture-progress"
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 6 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
        className={cn('mx-1 flex flex-col gap-1.5', className)}
      >
        <div className="text-muted-foreground flex items-center justify-between text-[11px] font-medium tabular-nums">
          <span>{ready ? 'Voice sample ready to clone' : 'Capturing your voice'}</span>
          <span>
            {clamped.toFixed(1)} / {CAPTURE_THRESHOLD_SECS}s
          </span>
        </div>
        <div className="bg-muted relative h-1.5 w-full overflow-hidden rounded-full">
          <motion.div
            className={cn(
              'absolute inset-y-0 left-0 rounded-full',
              ready ? 'bg-emerald-500' : 'bg-blue-500'
            )}
            initial={false}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
