import { ReactNode, useEffect, useRef } from 'react';
import { ConnectionState } from 'livekit-client';
import { toast as sonnerToast } from 'sonner';
import { useAgent, useConnectionState, useSessionContext } from '@livekit/components-react';
import { WarningIcon } from '@phosphor-icons/react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

interface ToastProps {
  title: ReactNode;
  description: ReactNode;
}

function toastAlert(toast: ToastProps) {
  const { title, description } = toast;

  return sonnerToast.custom(
    (id) => (
      <Alert onClick={() => sonnerToast.dismiss(id)} className="bg-accent w-full md:w-[364px]">
        <WarningIcon weight="bold" />
        <AlertTitle>{title}</AlertTitle>
        {description && <AlertDescription>{description}</AlertDescription>}
      </Alert>
    ),
    { duration: 10_000 }
  );
}

// `useAgent` raises state==='failed' for two very different situations, both surfaced via
// `failureReasons`. We only TEAR DOWN the call for the first:
//  - Startup failure ("Agent did not join the room." / "...did not complete initializing.")
//    → the session never really started; ending + toasting is correct.
//  - Mid-call agent blip ("Agent left the room unexpectedly.") → the agent participant
//    briefly dropped. That reason is STICKY (only clears on a full room disconnect), so the
//    old code's immediate end() killed an otherwise-live call on a transient blip — the
//    "crash mid-utterance". We now keep the call open (the pill shows "Reconnecting…") and
//    only end if the ROOM itself disconnects.
const STARTUP_FAILURE = /did not join|did not complete initializing/i;

export function useAgentErrors() {
  const agent = useAgent();
  const { isConnected, end } = useSessionContext();
  const connectionState = useConnectionState();
  // Toast the mid-call blip at most once per failure episode.
  const notifiedRef = useRef(false);

  useEffect(() => {
    if (!isConnected) return;

    if (agent.state !== 'failed') {
      notifiedRef.current = false;
      return;
    }

    const reasons = agent.failureReasons ?? [];
    // Logged so the exact reason is provable in the console next time it happens.
    console.warn('[useAgentErrors] agent state=failed', { reasons, connectionState });

    const startupFailure = reasons.some((r) => STARTUP_FAILURE.test(r));
    const roomGone = connectionState === ConnectionState.Disconnected;

    // Only end when the session genuinely can't continue.
    if (startupFailure || roomGone) {
      toastAlert({
        title: 'Session ended',
        description: (
          <>
            {reasons.length > 1 && (
              <ul className="list-inside list-disc">
                {reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
            {reasons.length === 1 && <p className="w-full">{reasons[0]}</p>}
            <p className="w-full">
              <a
                target="_blank"
                rel="noopener noreferrer"
                href="https://docs.livekit.io/agents/start/voice-ai/"
                className="whitespace-nowrap underline"
              >
                See quickstart guide
              </a>
              .
            </p>
          </>
        ),
      });
      end();
      return;
    }

    // Mid-call agent blip: keep the call open, just notify once.
    if (!notifiedRef.current) {
      notifiedRef.current = true;
      toastAlert({
        title: 'Reconnecting…',
        description: <p className="w-full">The agent connection dropped briefly. Hang tight.</p>,
      });
    }
  }, [agent, isConnected, end, connectionState]);
}
