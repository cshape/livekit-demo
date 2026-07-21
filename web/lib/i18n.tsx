'use client';

import { createContext, useContext } from 'react';

/**
 * Locale support for the demo. The default site (/) is English; /jp serves the
 * same app fully localized into Japanese — UI strings here, preset voices in
 * app-config.ts, and the agent's prompts/voices via the `lang` field the
 * frontend sends in the agent metadata (see components/app/app.tsx).
 */
export type Locale = 'en' | 'ja';

export interface UiStrings {
  /** Landing page */
  welcomeHeading: string;
  /** Description parts — casual/professional get highlighted spans between them. */
  descIntro: string;
  descCasual: string;
  descMid: string;
  descProfessional: string;
  descTail: string;

  /** Voice picker */
  orDivider: string;
  cloneTitle: string;
  cloneSubtitle: string;
  designTitle: string;
  designSubtitle: string;
  designPlaceholder: string;
  previewVoice: (name: string) => string;
  stopPreview: (name: string) => string;

  /** In-call UI */
  modeCasual: string;
  modeProfessional: string;
  stateListening: string;
  stateThinking: string;
  stateSpeaking: string;
  stateConnecting: string;
  reconnecting: string;
  preConnectMessage: string;
  endCall: string;
  endCallShort: string;
  startAudio: string;

  /** Clone / design overlay cards */
  cloneReadPrompt: string;
  cloneKeepReading: (seconds: number) => string;
  cloneBuilding: string;
  designBuilding: string;

  /** /chat-to-clone landing + in-call capture indicator */
  chatCloneHeading: string;
  chatCloneDescription: string;
  chatCloneCapturing: string;
}

export const UI_STRINGS: Record<Locale, UiStrings> = {
  en: {
    welcomeHeading: 'Hear Fish Audio’s expressive voices',
    descIntro: 'A voice agent powered by Fish Audio’s expressive text-to-speech. Flip it between ',
    descCasual: 'casual',
    descMid: ' and ',
    descProfessional: 'professional',
    descTail:
      ' to change style. Pick a voice to start, clone your own, or design one from scratch.',

    orDivider: 'or',
    cloneTitle: 'Clone your voice',
    cloneSubtitle: 'Read a short script — talk to an expressive version of yourself',
    designTitle: 'Design a voice',
    designSubtitle: 'Describe a voice in words — it’s built on the spot',
    designPlaceholder:
      'e.g. energetic young presenter, bright tone, crisp diction, friendly but not cartoonish',
    previewVoice: (name) => `Preview ${name}`,
    stopPreview: (name) => `Stop ${name} preview`,

    modeCasual: 'Casual',
    modeProfessional: 'Professional',
    stateListening: 'listening',
    stateThinking: 'thinking',
    stateSpeaking: 'speaking',
    stateConnecting: 'connecting',
    reconnecting: 'Reconnecting…',
    preConnectMessage: 'Agent is listening, ask it a question',
    endCall: 'END CALL',
    endCallShort: 'END',
    startAudio: 'Start Audio',

    cloneReadPrompt: 'Read this aloud to clone your voice',
    cloneKeepReading: (seconds) => `Keep reading — cloning in ${seconds}s`,
    cloneBuilding: 'Cloning your voice',
    designBuilding: 'Designing your voice',

    chatCloneHeading: 'Talk, and hear yourself',
    chatCloneDescription:
      'Just start chatting. After about ten seconds of your voice, the agent clones you on the spot and keeps talking — in your own voice. Your recording and the clone are deleted when the call ends.',
    chatCloneCapturing: 'Keep chatting — cloning your voice',
  },
  ja: {
    welcomeHeading: 'Fish Audioの表現力豊かな声を体験',
    descIntro: 'Fish Audioの表現力豊かな音声合成で動くボイスエージェントです。',
    descCasual: 'カジュアル',
    descMid: 'と',
    descProfessional: 'フォーマル',
    descTail:
      'の切り替えで話し方が変わります。声を選んで通話を始めるか、自分の声をクローン、またはゼロからデザインしてみてください。',

    orDivider: 'または',
    cloneTitle: '自分の声をクローン',
    cloneSubtitle: '短いスクリプトを読むだけ — 表現力豊かなあなた自身の声と話せます',
    designTitle: '声をデザイン',
    designSubtitle: '言葉で声を描写すると、その場で新しい声が生まれます',
    designPlaceholder:
      '例：元気な若手アナウンサー、明るいトーン、はきはきした話し方、親しみやすい声',
    previewVoice: (name) => `${name}を試聴`,
    stopPreview: (name) => `${name}の試聴を停止`,

    modeCasual: 'カジュアル',
    modeProfessional: 'フォーマル',
    stateListening: '聞いています',
    stateThinking: '考え中',
    stateSpeaking: '話しています',
    stateConnecting: '接続中',
    reconnecting: '再接続中…',
    preConnectMessage: 'エージェントが聞いています — 話しかけてみてください',
    endCall: '通話終了',
    endCallShort: '終了',
    startAudio: '音声を開始',

    cloneReadPrompt: '声をクローンします — 声に出して読んでください',
    cloneKeepReading: (seconds) => `そのまま読み続けてください — あと${seconds}秒`,
    cloneBuilding: 'あなたの声をクローン中',
    designBuilding: '声をデザイン中',

    chatCloneHeading: '話すだけで、あなたの声に',
    chatCloneDescription:
      'まずは話しかけてください。あなたの声が10秒ほど集まると、その場でクローンが作られ、エージェントはあなた自身の声で話し続けます。録音とクローンは通話終了時に削除されます。',
    chatCloneCapturing: 'そのまま話し続けてください — 声をクローン中',
  },
};

const LocaleContext = createContext<Locale>('en');

export function LocaleProvider({
  locale,
  children,
}: {
  locale: Locale;
  children: React.ReactNode;
}) {
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

export function useLocale(): Locale {
  return useContext(LocaleContext);
}

export function useStrings(): UiStrings {
  return UI_STRINGS[useLocale()];
}
