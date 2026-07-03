'use client';

import { useEffect, useState } from 'react';
import type { LocalAudioTrack, RemoteParticipant } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import {
  useLocalParticipant,
  useMultibandTrackVolume,
  useParticipantAttribute,
  useVoiceAssistant,
} from '@livekit/components-react';
import { MicrophoneIcon } from '@phosphor-icons/react/dist/ssr';
import { AgentChatIndicator } from '@/components/agents-ui/agent-chat-indicator';
import { cn } from '@/lib/shadcn/utils';

// Mirrors CLONE_READ_SECS in fish/src/agent.py; the agent also publishes it as
// `clone.read_secs`, which wins over this fallback.
const DEFAULT_READ_SECS = 15;

const WAVEFORM_BANDS = 20;

// Subtle waveform driven by the LOCAL mic level — live feedback that the reading is
// being heard. Bars sit at a faint minimum when silent and swell while speaking.
function MicWaveform() {
  const { microphoneTrack } = useLocalParticipant();
  const volumes = useMultibandTrackVolume(microphoneTrack?.track as LocalAudioTrack | undefined, {
    bands: WAVEFORM_BANDS,
  });
  const bands = volumes.length === WAVEFORM_BANDS ? volumes : Array(WAVEFORM_BANDS).fill(0);
  return (
    <div className="flex h-5 items-center justify-center gap-1" aria-hidden="true">
      {bands.map((volume, i) => (
        <span
          key={i}
          className="bg-primary/60 w-1 rounded-full transition-[height] duration-100 ease-out"
          style={{ height: `${3 + Math.min(1, volume) * 17}px` }}
        />
      ))}
    </div>
  );
}

export function CloneScriptCard({ className }: { className?: string }) {
  const { agent } = useVoiceAssistant();
  if (!agent) return null;
  return <CloneScriptCardInner agent={agent} className={className} />;
}

function CloneScriptCardInner({
  agent,
  className,
}: {
  agent: RemoteParticipant;
  className?: string;
}) {
  const state = useParticipantAttribute('clone.state', { participant: agent });
  const script = useParticipantAttribute('clone.script', { participant: agent }) ?? '';
  const rawReadSecs = useParticipantAttribute('clone.read_secs', { participant: agent });

  const readSecs = Number(rawReadSecs) > 0 ? Number(rawReadSecs) : DEFAULT_READ_SECS;
  const reading = state === 'reading';
  const cloning = state === 'cloning';
  const show = (state === 'prompt' || reading || cloning) && Boolean(script);

  // Local mirror of the agent's fixed read window: counts down from readSecs once
  // clone.state flips to "reading". Display-only — the agent runs the authoritative
  // timer and clones whatever it captured when its own window closes.
  const [remaining, setRemaining] = useState(readSecs);
  useEffect(() => {
    if (!reading) {
      setRemaining(readSecs);
      return;
    }
    const startedAt = performance.now();
    const id = setInterval(() => {
      setRemaining(Math.max(0, readSecs - (performance.now() - startedAt) / 1000));
    }, 100);
    return () => clearInterval(id);
  }, [reading, readSecs]);

  const progress = reading ? Math.min(1, Math.max(0, 1 - remaining / readSecs)) : 0;

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          key="clone-script-card"
          initial={{ opacity: 0, y: 8, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 8, scale: 0.98 }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
          className={cn(
            'border-border bg-background/95 pointer-events-none mx-auto w-full max-w-md rounded-2xl border p-6 shadow-lg backdrop-blur',
            className
          )}
        >
          {cloning ? (
            <div className="flex flex-col items-center gap-4 py-4">
              <div className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                Cloning your voice
              </div>
              <AgentChatIndicator size="md" />
            </div>
          ) : (
            <>
              <div className="text-muted-foreground flex items-center justify-center gap-2 text-xs font-medium tracking-wide uppercase">
                <MicrophoneIcon weight="fill" className="size-4" />
                {reading
                  ? `Keep reading — cloning in ${Math.ceil(remaining)}s`
                  : 'Read this aloud to clone your voice'}
              </div>

              <p className="text-foreground mt-4 text-center text-lg leading-relaxed text-pretty">
                {script}
              </p>

              {/* Live "we hear you" waveform (local mic level) */}
              <div className="mt-4">
                <MicWaveform />
              </div>

              {/* Countdown bar for the fixed read window */}
              <div className="bg-muted mt-3 h-1 w-full overflow-hidden rounded-full">
                <div
                  className="bg-primary h-full rounded-full transition-[width] duration-100 ease-linear"
                  style={{ width: `${progress * 100}%` }}
                />
              </div>
            </>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
