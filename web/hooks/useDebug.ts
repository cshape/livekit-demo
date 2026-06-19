import * as React from 'react';
import { LogLevel, setLogExtension, setLogLevel } from 'livekit-client';
import { useRoomContext } from '@livekit/components-react';
import { pushDebugLog } from '@/lib/debug-store';

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
      pushDebugLog({
        level: LogLevel[level] ?? String(level),
        source: 'livekit',
        message: `${msg}${ctx}`,
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
