'use client';

import type { RemoteParticipant } from 'livekit-client';
import { ArrowRightIcon } from 'lucide-react';
import { motion } from 'motion/react';
import { useParticipantAttribute, useVoiceAssistant } from '@livekit/components-react';

const FISH_URL = 'https://fish.audio?utm_source=livekit-demo';

/**
 * Stylized sign-up call-to-action shown in the chat once the agent has switched
 * to the user's cloned voice (`clone.state === "playing"`). The demo clone is
 * deleted when the call ends, so this nudges them to create a permanent one at
 * fish.audio. Self-gating like CloneStatusBanner: renders nothing until the
 * agent participant exists and the voice has actually switched.
 */
export function FishCta() {
  const { agent } = useVoiceAssistant();
  if (!agent) return null;
  return <FishCtaInner agent={agent} />;
}

function FishCtaInner({ agent }: { agent: RemoteParticipant }) {
  const state = useParticipantAttribute('clone.state', { participant: agent });
  if (state !== 'playing') return null;

  return (
    <motion.a
      href={FISH_URL}
      target="_blank"
      rel="noopener noreferrer"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className="group mx-auto block w-full max-w-md rounded-2xl bg-gradient-to-br from-sky-500/15 via-cyan-500/10 to-emerald-500/15 p-px ring-1 ring-sky-500/30 transition-shadow hover:shadow-lg hover:shadow-sky-500/10 hover:ring-sky-400/60"
    >
      <div className="bg-background/80 rounded-[15px] px-4 py-3.5 backdrop-blur">
        <div className="flex items-center gap-3">
          <span className="text-2xl leading-none" aria-hidden>
            🐟
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-foreground text-sm font-semibold">Keep this voice forever</p>
            <p className="text-muted-foreground text-xs">
              This clone vanishes when the call ends. Create a permanent one and explore thousands
              more voices at fish.audio.
            </p>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-end">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-sky-500 px-3.5 py-1.5 text-xs font-semibold text-white transition-colors group-hover:bg-sky-400">
            Sign up at fish.audio
            <ArrowRightIcon className="size-3.5 transition-transform group-hover:translate-x-0.5" />
          </span>
        </div>
      </div>
    </motion.a>
  );
}
