'use client';

import type { RemoteParticipant } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import { useParticipantAttribute, useVoiceAssistant } from '@livekit/components-react';
import { MicrophoneIcon } from '@phosphor-icons/react/dist/ssr';
import { AgentChatIndicator } from '@/components/agents-ui/agent-chat-indicator';
import { useStrings } from '@/lib/i18n';
import { cn } from '@/lib/shadcn/utils';

// Compact in-call indicator for the /chat-to-clone flow. Unlike the clone-first
// script card (a big centered overlay), this is a slim top pill that never covers
// the conversation: a capture progress bar while we buffer the user's voice, then a
// brief "cloning" pulse, then it disappears once the cloned voice takes over. The
// agent drives it via `clone.state` / `clone.capture_secs` / `clone.threshold_secs`
// (only ever set on chat-to-clone sessions), so it's inert everywhere else.
export function ChatCloneStatus({ className }: { className?: string }) {
  const { agent } = useVoiceAssistant();
  if (!agent) return null;
  return <ChatCloneStatusInner agent={agent} className={className} />;
}

function ChatCloneStatusInner({
  agent,
  className,
}: {
  agent: RemoteParticipant;
  className?: string;
}) {
  const strings = useStrings();
  const state = useParticipantAttribute('clone.state', { participant: agent });
  const rawThreshold = useParticipantAttribute('clone.threshold_secs', { participant: agent });
  const rawCaptured = useParticipantAttribute('clone.capture_secs', { participant: agent });

  const threshold = Number(rawThreshold);
  // Only a chat-to-clone session publishes threshold_secs; without it, render nothing.
  if (!(threshold > 0)) return null;

  const capturing = state === 'chatting';
  const cloning = state === 'cloning' || state === 'ready';
  const show = capturing || cloning;

  const captured = Math.max(0, Number(rawCaptured) || 0);
  const progress = Math.min(1, captured / threshold);

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          key="chat-clone-status"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 8 }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
          className={cn(
            'border-border bg-background/95 pointer-events-none flex w-full max-w-xs flex-col gap-2 rounded-3xl border px-4 pt-2.5 pb-4 backdrop-blur',
            className
          )}
        >
          <div className="text-muted-foreground flex items-center justify-center gap-2 text-xs font-medium tracking-wide">
            {cloning ? (
              <>
                <AgentChatIndicator size="sm" />
                <span className="uppercase">{strings.cloneBuilding}</span>
              </>
            ) : (
              <>
                <MicrophoneIcon weight="fill" className="size-4" />
                <span>{strings.chatCloneCapturing}</span>
              </>
            )}
          </div>
          {capturing && (
            <div className="bg-muted h-1 w-full overflow-hidden rounded-full">
              <div
                className="bg-primary h-full rounded-full transition-[width] duration-300 ease-out"
                style={{ width: `${progress * 100}%` }}
              />
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
