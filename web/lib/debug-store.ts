'use client';

import { useSyncExternalStore } from 'react';

/**
 * Tiny external store backing the hidden `/debug` overlay. Holds whether the
 * overlay is open plus a rolling buffer of log lines (LiveKit client logs,
 * clone-state transitions, etc.). Kept outside React so non-component code —
 * e.g. the LiveKit `setLogExtension` callback — can append to it.
 */

export type DebugLogSource = 'livekit' | 'clone' | 'system';

export interface DebugLogEntry {
  id: number;
  ts: number;
  level: string;
  source: DebugLogSource;
  message: string;
}

interface DebugState {
  enabled: boolean;
  logs: DebugLogEntry[];
}

// Cap the buffer so a chatty session can't grow it without bound.
const MAX_LOGS = 400;

let state: DebugState = { enabled: false, logs: [] };
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function setState(next: Partial<DebugState>) {
  state = { ...state, ...next };
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function isDebugEnabled() {
  return state.enabled;
}

export function setDebugEnabled(enabled: boolean) {
  if (state.enabled !== enabled) setState({ enabled });
}

export function toggleDebug() {
  setState({ enabled: !state.enabled });
  return state.enabled;
}

export function pushDebugLog(entry: { level: string; source: DebugLogSource; message: string }) {
  const log: DebugLogEntry = {
    id: nextId++,
    ts: Date.now(),
    level: entry.level,
    source: entry.source,
    message: entry.message,
  };
  setState({ logs: [...state.logs, log].slice(-MAX_LOGS) });
}

export function clearDebugLogs() {
  setState({ logs: [] });
}

export function useDebugState(): DebugState {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => state
  );
}
