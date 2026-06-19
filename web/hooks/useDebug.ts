import * as React from 'react';
import { LogLevel, setLogExtension, setLogLevel } from 'livekit-client';
import { useRoomContext } from '@livekit/components-react';
import { pushDebugLog } from '@/lib/debug-store';

// High-frequency, benign LiveKit log lines that drown out the useful ones. The
// `lk.agent.session` byte stream is published by the Python agents SDK on a
// topic no released web SDK consumes yet (so the client logs "no handler" ~1/s);
// `update publication info` is routine track-publication churn. Neither tells us
// anything actionable, so we drop them before they reach the overlay.
const DEBUG_LOG_DENYLIST = ['lk.agent.session', 'update publication info'];

/**
 * Tee every LiveKit client log line into the debug store so the hidden `/debug`
 * overlay can show them. Registered once near the app root; the buffer fills
 * whether or not the overlay is open, so it already has history the moment you
 * reveal it.
 */
export const useDebugLogCapture = (enabled = true) => {
  React.useEffect(() => {
    if (!enabled) return;
    setLogExtension((level, msg, context) => {
      const ctx = context && Object.keys(context).length > 0 ? ` ${JSON.stringify(context)}` : '';
      const message = `${msg}${ctx}`;
      if (DEBUG_LOG_DENYLIST.some((pattern) => message.includes(pattern))) return;
      pushDebugLog({
        level: LogLevel[level] ?? String(level),
        source: 'livekit',
        message,
      });
    });
    return () => {
      // Reset to a no-op extension on unmount.
      setLogExtension(() => {});
    };
  }, [enabled]);
};

export const useDebugMode = (options: { logLevel?: LogLevel; enabled?: boolean } = {}) => {
  const room = useRoomContext();
  const logLevel = options.logLevel ?? 'debug';
  const enabled = options.enabled ?? true;

  React.useEffect(() => {
    if (!enabled) {
      setLogLevel('silent');
      return;
    }

    setLogLevel(logLevel ?? 'debug');

    // @ts-expect-error this is a global variable
    window.__lk_room = room;

    return () => {
      // @ts-expect-error this is a global variable
      window.__lk_room = undefined;
      setLogLevel('silent');
    };
  }, [room, enabled, logLevel]);
};
