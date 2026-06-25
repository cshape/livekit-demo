import { useEffect, useRef } from 'react';
import { useAgent, useConnectionState, useSessionContext } from '@livekit/components-react';

// This used to call session.end() (-> room.disconnect()) the instant agent.state became
// 'failed'. That was the "crash mid-convo": rapid casual<->professional switches make the
// SDK spuriously flip agent.state to 'failed' (a stale agent-connect/initialize signal)
// while the room is still fully connected and the agent is still talking. Ending there
// tore down a live call.
//
// So we NEVER end the call from here anymore. The mood pill already surfaces 'failed' as
// "Reconnecting…", and the user can hit END manually if it's genuinely dead. We just log
// the failure reason for diagnostics. (A real network/room loss is handled by the room
// lifecycle itself, not by this hook.)
export function useAgentErrors() {
  const agent = useAgent();
  const { isConnected } = useSessionContext();
  const connectionState = useConnectionState();
  const loggedRef = useRef(false);

  useEffect(() => {
    if (!isConnected || agent.state !== 'failed') {
      loggedRef.current = false;
      return;
    }
    if (!loggedRef.current) {
      loggedRef.current = true;
      console.warn('[useAgentErrors] agent state=failed (keeping the call open)', {
        reasons: agent.failureReasons,
        connectionState,
      });
    }
  }, [agent, isConnected, connectionState]);
}
