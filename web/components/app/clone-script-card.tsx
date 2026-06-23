'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { RemoteParticipant } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import { useParticipantAttribute, useVoiceAssistant } from '@livekit/components-react';
import { MicrophoneIcon } from '@phosphor-icons/react/dist/ssr';
import { AgentChatIndicator } from '@/components/agents-ui/agent-chat-indicator';
import { cn } from '@/lib/shadcn/utils';

// Seconds at which the time-based highlight fallback reaches the end of the script.
// Just a floor so the highlight keeps moving if STT lags — the actual clone trigger
// is time-of-speech based on the backend (CLONE_SCRIPT_TARGET_SECS).
const SCRIPT_TARGET_SECS = 14;

function normalize(word: string): string {
  return word.toLowerCase().replace(/[^a-z0-9']/g, '');
}

// Small bounded edit distance — returns true if within `max` edits. Used so STT
// near-misses (e.g. "harbour" vs "harbor") still count as a match.
function withinEdits(a: string, b: string, max: number): boolean {
  if (Math.abs(a.length - b.length) > max) return false;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let best = i;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      const v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      cur.push(v);
      if (v < best) best = v;
    }
    if (best > max) return false; // whole row already exceeds budget
    prev = cur;
  }
  return prev[b.length] <= max;
}

function wordsMatch(heard: string, script: string): boolean {
  if (!heard || !script) return false;
  if (heard === script) return true;
  // Prefix match handles STT cutting a word short or adding a suffix.
  if (
    heard.length >= 3 &&
    script.length >= 3 &&
    (heard.startsWith(script) || script.startsWith(heard))
  )
    return true;
  // Fuzzy: allow 1 edit for short words, 2 for longer ones.
  return withinEdits(heard, script, script.length >= 6 ? 2 : 1);
}

// Align the heard transcript against the script words and return how many script
// words have been read. Greedy with a forward window (skip ahead past STT drops)
// and a small backward window (recover when we got slightly ahead).
function matchedWordCount(scriptWords: string[], heard: string): number {
  const H = heard.split(/\s+/).map(normalize).filter(Boolean);
  if (!H.length || !scriptWords.length) return 0;
  const FWD = 6;
  const BACK = 2;
  let si = 0;
  for (const h of H) {
    let found = -1;
    for (let j = si; j < Math.min(scriptWords.length, si + FWD); j++) {
      if (wordsMatch(h, scriptWords[j])) {
        found = j;
        break;
      }
    }
    if (found === -1) {
      for (let j = si - 1; j >= Math.max(0, si - BACK); j--) {
        if (wordsMatch(h, scriptWords[j])) {
          found = j;
          break;
        }
      }
    }
    if (found !== -1) si = found + 1;
    // else: unmatched heard word (STT noise) — skip it.
  }
  return si;
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
  const heard = useParticipantAttribute('clone.heard', { participant: agent }) ?? '';
  const rawSecs = useParticipantAttribute('clone.capture_secs', { participant: agent });

  const reading = state === 'prompt';
  const cloning = state === 'cloning';
  const show = (reading || cloning) && Boolean(script);

  const words = useMemo(() => script.split(/\s+/).filter(Boolean), [script]);
  const normWords = useMemo(() => words.map(normalize), [words]);

  // Primary signal: how many words the STT says we've read.
  const matched = useMemo(() => matchedWordCount(normWords, heard), [normWords, heard]);

  // Fallback: once the user starts speaking, advance a time floor so the
  // highlight keeps progressing even if STT lags or returns nothing.
  const secs = Number.isFinite(Number(rawSecs)) ? Number(rawSecs) : 0;
  const speechStarted = heard.trim().length > 0 || secs > 0;
  const startRef = useRef<number | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!show) {
      startRef.current = null;
      setElapsed(0);
    }
  }, [show]);

  useEffect(() => {
    if (show && speechStarted && startRef.current === null) {
      startRef.current = performance.now();
    }
  }, [show, speechStarted]);

  useEffect(() => {
    if (!show) return;
    const id = setInterval(() => {
      if (startRef.current !== null) {
        setElapsed((performance.now() - startRef.current) / 1000);
      }
    }, 150);
    return () => clearInterval(id);
  }, [show]);

  const timeFloor = Math.floor((elapsed / SCRIPT_TARGET_SECS) * words.length);
  const highlightCount = Math.min(words.length, Math.max(matched, timeFloor));

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
                Read this aloud to clone your voice
              </div>

              <p className="mt-4 text-center text-lg leading-relaxed text-pretty">
                {words.map((word, i) => (
                  <span
                    key={i}
                    className={cn(
                      'transition-colors duration-200',
                      i < highlightCount
                        ? 'text-foreground font-medium'
                        : 'text-muted-foreground/40'
                    )}
                  >
                    {word}{' '}
                  </span>
                ))}
              </p>
            </>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
