'use client';

import { type ComponentProps } from 'react';
import { AnimatePresence } from 'motion/react';
import { type AgentState, type ReceivedMessage } from '@livekit/components-react';
import { AgentChatIndicator } from '@/components/agents-ui/agent-chat-indicator';
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from '@/components/ai-elements/conversation';
import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message';

// Strip Fish Audio [emotion] markers (e.g. "[excited] Got it!") so they
// don't render in the chat transcript — they're TTS-only and look like noise
// on screen.
function stripEmotionTags(text: string): string {
  return (
    text
      // Complete [tag] markers.
      .replace(/\[[^\]]*\]/g, '')
      // A still-streaming, not-yet-closed tag (e.g. "[speaks warmly" before the
      // "]" arrives). Without this it briefly renders as raw text — and Streamdown
      // reads the "[" as the start of a markdown link, flashing it blue — until the
      // closing bracket lands and the complete-tag rule above removes it. Hide it
      // from the trailing "[" to end-of-string so nothing flickers mid-stream.
      .replace(/\[[^\]]*$/, '')
      .replace(/\s+/g, ' ')
      .trim()
  );
}

// The agent speaks the website as "fish dot audio" so the TTS pronounces the
// domain correctly. In the transcript we turn that (and any stray "fish.audio")
// into a clickable, correctly-spelled fish.audio link.
const FISH_URL = 'https://fish.audio?utm_source=livekit-demo';
function linkifyFishAudio(text: string): string {
  return text.replace(/\bfish(?:\s+dot\s+|\.)audio\b/gi, `[fish.audio](${FISH_URL})`);
}

// While "fish dot audio" is still streaming in word-by-word, the partial
// ("fish dot", "fish dot aud"…) shows as plain text until the whole phrase
// lands and linkifyFishAudio turns it into the link — so "fish dot audio"
// flashes momentarily. Hide a trailing, not-yet-complete phrase. We require the
// "dot" word (or "fish." followed by an audio letter) so a sentence that simply
// ends in "fish" or "fish." stays untouched.
function hideStreamingFishPartial(text: string): string {
  return text
    .replace(/\bfish(?:\s+dot\b\s*(?:audi|aud|au|a)?|\.(?:audi|aud|au|a))$/i, '')
    .trimEnd();
}

/**
 * Props for the AgentChatTranscript component.
 */
export interface AgentChatTranscriptProps extends ComponentProps<'div'> {
  /**
   * The current state of the agent. When 'thinking', displays a loading indicator.
   */
  agentState?: AgentState;
  /**
   * Array of messages to display in the transcript.
   * @defaultValue []
   */
  messages?: ReceivedMessage[];
  /**
   * Additional CSS class names to apply to the conversation container.
   */
  className?: string;
}

/**
 * A chat transcript component that displays a conversation between the user and agent.
 * Shows messages with timestamps and origin indicators, plus a thinking indicator
 * when the agent is processing.
 *
 * @extends ComponentProps<'div'>
 *
 * @example
 * ```tsx
 * <AgentChatTranscript
 *   agentState={agentState}
 *   messages={chatMessages}
 * />
 * ```
 */
export function AgentChatTranscript({
  agentState,
  messages = [],
  className,
  ...props
}: AgentChatTranscriptProps) {
  return (
    <Conversation className={className} {...props}>
      <ConversationContent>
        {messages.map((receivedMessage) => {
          const { id, timestamp, from, message } = receivedMessage;
          const locale = navigator?.language ?? 'en-US';
          const messageOrigin = from?.isLocal ? 'user' : 'assistant';
          const time = new Date(timestamp);
          const title = time.toLocaleTimeString(locale, { timeStyle: 'full' });

          return (
            <Message key={id} title={title} from={messageOrigin}>
              <MessageContent>
                <MessageResponse className="[&_a]:font-medium [&_a]:text-sky-500 [&_a]:underline [&_a]:underline-offset-2 hover:[&_a]:text-sky-400">
                  {linkifyFishAudio(hideStreamingFishPartial(stripEmotionTags(message)))}
                </MessageResponse>
              </MessageContent>
            </Message>
          );
        })}
        <AnimatePresence>
          {agentState === 'thinking' && <AgentChatIndicator size="sm" />}
        </AnimatePresence>
      </ConversationContent>
      <ConversationScrollButton />
    </Conversation>
  );
}
