'use client';

import type { RemoteParticipant } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import { useParticipantAttribute, useVoiceAssistant } from '@livekit/components-react';
import { SparkleIcon } from '@phosphor-icons/react/dist/ssr';
import { AgentChatIndicator } from '@/components/agents-ui/agent-chat-indicator';
import { cn } from '@/lib/shadcn/utils';

// Centered overlay shown while the agent builds the designed voice
// (design.state === 'designing'); it disappears on 'ready'/'failed'.
export function DesignStatusCard({ className }: { className?: string }) {
  const { agent } = useVoiceAssistant();
  if (!agent) return null;
  return <DesignStatusCardInner agent={agent} className={className} />;
}

function DesignStatusCardInner({
  agent,
  className,
}: {
  agent: RemoteParticipant;
  className?: string;
}) {
  const state = useParticipantAttribute('design.state', { participant: agent });

  return (
    <AnimatePresence>
      {state === 'designing' && (
        <motion.div
          key="design-status-card"
          initial={{ opacity: 0, y: 8, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 8, scale: 0.98 }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
          className={cn(
            'border-border bg-background/95 pointer-events-none mx-auto w-full max-w-md rounded-2xl border p-6 shadow-lg backdrop-blur',
            className
          )}
        >
          <div className="flex flex-col items-center gap-4 py-4">
            <div className="text-muted-foreground flex items-center gap-2 text-xs font-medium tracking-wide uppercase">
              <SparkleIcon weight="fill" className="size-4" />
              Designing your voice
            </div>
            <AgentChatIndicator size="md" />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
