'use client';

import { type ComponentProps, useRef } from 'react';
import type { RemoteParticipant } from 'livekit-client';
import { AnimatePresence } from 'motion/react';
import {
  type AgentState,
  type ReceivedMessage,
  useParticipantAttribute,
  useVoiceAssistant,
} from '@livekit/components-react';
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
      // Safety net: the prompt tells the model to keep sound effects inside
      // [brackets] with no spoken text, but it occasionally freelances a stray
      // laugh/sigh as "(heh)", "*laughs*", or bare "haha"/"heh heh". Strip those
      // known tokens so they neither render nor read as noise. Deliberately
      // narrow — we don't strip all parentheses.
      .replace(
        /[(*]\s*(?:chuckl\w*|laugh\w*|sigh\w*|groan\w*|gasp\w*|yawn\w*|hehe?|haha?|ahem)\s*[)*]/gi,
        ''
      )
      .replace(/\b(?:(?:heh|hah?|ha)[\s,]*){2,}/gi, '')
      // The model sometimes wraps its delivery tags in backticks (mirroring how
      // the prompt formats them, e.g. `[playful]`). The [tag] strip above removes
      // the inside but leaves the backticks orphaned, so drop any stray backticks
      // (and asterisks) — a voice reply never has legitimate markdown formatting.
      .replace(/[`*]+/g, '')
      .replace(/\s+([,.!?])/g, '$1')
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
function MessageRow({ receivedMessage }: { receivedMessage: ReceivedMessage }) {
  const { timestamp, from, message } = receivedMessage;
  const locale = navigator?.language ?? 'en-US';
  const messageOrigin = from?.isLocal ? 'user' : 'assistant';
  const time = new Date(timestamp);
  const title = time.toLocaleTimeString(locale, { timeStyle: 'full' });

  return (
    <Message title={title} from={messageOrigin}>
      <MessageContent>
        <MessageResponse className="[&_a]:font-medium [&_a]:text-sky-500 [&_a]:underline [&_a]:underline-offset-2 hover:[&_a]:text-sky-400">
          {linkifyFishAudio(hideStreamingFishPartial(stripEmotionTags(message)))}
        </MessageResponse>
      </MessageContent>
    </Message>
  );
}

// Messages spoken/heard during the clone-script read shouldn't land in the chat
// (the user reading the script, the agent's read prompt/ack). We hide any message
// seen while clone.state is 'prompt' or 'cloning'; the set persists so they stay
// hidden once the real conversation begins.
function FilteredMessages({
  agent,
  messages,
}: {
  agent: RemoteParticipant;
  messages: ReceivedMessage[];
}) {
  const cloneState = useParticipantAttribute('clone.state', { participant: agent });
  const hiddenRef = useRef<Set<string>>(new Set());
  if (cloneState === 'prompt' || cloneState === 'cloning') {
    for (const m of messages) hiddenRef.current.add(m.id);
  }
  const visible = messages.filter((m) => !hiddenRef.current.has(m.id));
  return (
    <>
      {visible.map((m) => (
        <MessageRow key={m.id} receivedMessage={m} />
      ))}
    </>
  );
}

function TranscriptMessages({ messages }: { messages: ReceivedMessage[] }) {
  const { agent } = useVoiceAssistant();
  if (!agent) {
    return (
      <>
        {messages.map((m) => (
          <MessageRow key={m.id} receivedMessage={m} />
        ))}
      </>
    );
  }
  return <FilteredMessages agent={agent} messages={messages} />;
}

export function AgentChatTranscript({
  agentState,
  messages = [],
  className,
  ...props
}: AgentChatTranscriptProps) {
  return (
    <Conversation className={className} {...props}>
      <ConversationContent>
        <TranscriptMessages messages={messages} />
        <ThinkingIndicator agentState={agentState} />
      </ConversationContent>
      <ConversationScrollButton />
    </Conversation>
  );
}

// Shows the "preparing a response" dots when the agent is thinking. (The clone
// build has its own loading dot inside the clone-script card, so it's not shown
// here to avoid a duplicate.)
function ThinkingIndicator({ agentState }: { agentState?: AgentState }) {
  return (
    <AnimatePresence>
      {agentState === 'thinking' && <AgentChatIndicator size="sm" />}
    </AnimatePresence>
  );
}
