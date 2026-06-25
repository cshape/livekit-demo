'use client';

import { useEffect, useState } from 'react';
import type { RemoteParticipant } from 'livekit-client';
import { motion } from 'motion/react';
import {
  useParticipantAttribute,
  useRoomContext,
  useVoiceAssistant,
} from '@livekit/components-react';
import { cn } from '@/lib/shadcn/utils';

// The two speaking registers the user can flip between. Switching is user-driven:
// we call the agent's `set_mode` RPC, which swaps its expressive preset and fires a
// short demo line in the new voice. The agent echoes the applied register back via
// the `style.mode` attribute, which we reconcile against (handles confirms + any
// out-of-band change).
const MODES = [
  { key: 'casual', label: 'Casual' },
  { key: 'professional', label: 'Professional' },
] as const;
type ModeKey = (typeof MODES)[number]['key'];

interface ModeToggleProps {
  className?: string;
}

export function ModeToggle({ className }: ModeToggleProps) {
  const { agent } = useVoiceAssistant();
  // useParticipantAttribute throws without a participant — only mount the inner
  // (which calls the hook) once the agent has actually joined.
  if (!agent) return null;
  return <ModeToggleInner agent={agent} className={className} />;
}

function ModeToggleInner({ agent, className }: { agent: RemoteParticipant; className?: string }) {
  const room = useRoomContext();
  const attrMode = useParticipantAttribute('style.mode', { participant: agent });
  const [mode, setMode] = useState<ModeKey>('casual');
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (attrMode === 'casual' || attrMode === 'professional') setMode(attrMode);
  }, [attrMode]);

  const switchTo = async (next: ModeKey) => {
    if (next === mode || pending) return;
    const prev = mode;
    setMode(next); // optimistic — snap immediately, reconcile/revert below
    setPending(true);
    try {
      await room.localParticipant.performRpc({
        destinationIdentity: agent.identity,
        method: 'set_mode',
        payload: next,
      });
    } catch (err) {
      console.error('set_mode RPC failed', err);
      setMode(prev);
    } finally {
      setPending(false);
    }
  };

  return (
    <div
      role="group"
      aria-label="Speaking register"
      className={cn(
        'border-border/60 bg-background/80 relative inline-flex items-center rounded-full border p-1 backdrop-blur',
        className
      )}
    >
      {MODES.map((m) => {
        const active = m.key === mode;
        return (
          <button
            key={m.key}
            type="button"
            disabled={pending}
            aria-pressed={active}
            onClick={() => switchTo(m.key)}
            className={cn(
              'relative z-10 rounded-full px-3.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed',
              active ? 'text-background' : 'text-foreground/60 hover:text-foreground'
            )}
          >
            {active && (
              <motion.span
                layoutId="mode-toggle-active"
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                className="bg-foreground absolute inset-0 -z-10 rounded-full"
              />
            )}
            {m.label}
          </button>
        );
      })}
    </div>
  );
}
