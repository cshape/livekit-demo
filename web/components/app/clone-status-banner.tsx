'use client';

import type { RemoteParticipant } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import { useParticipantAttribute, useVoiceAssistant } from '@livekit/components-react';
import { cn } from '@/lib/shadcn/utils';

type CloneState = 'idle' | 'cloning' | 'ready' | 'playing';

const PILL_META: Partial<Record<CloneState, { label: string; tone: string; spinner?: boolean }>> = {
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
  const pill = PILL_META[state];

  return (
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
  );
}
