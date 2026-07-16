'use client';

import { useEffect, useRef, useState } from 'react';
import { MicrophoneIcon, PauseIcon, PlayIcon, SparkleIcon } from '@phosphor-icons/react/dist/ssr';
import { CLONE_SELECTION, DESIGN_SELECTION, getPresetVoices } from '@/app-config';
import { useLocale, useStrings } from '@/lib/i18n';
import { cn } from '@/lib/shadcn/utils';

interface VoicePickerProps {
  selection: string;
  onSelectionChange: (selection: string) => void;
  designInstruction: string;
  onDesignInstructionChange: (value: string) => void;
}

export function VoicePicker({
  selection,
  onSelectionChange,
  designInstruction,
  onDesignInstructionChange,
}: VoicePickerProps) {
  const strings = useStrings();
  const presetVoices = getPresetVoices(useLocale());
  // One shared audio element; previewing a voice stops any other preview.
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
    };
  }, []);

  const togglePreview = (id: string, url: string) => {
    let audio = audioRef.current;
    if (!audio) {
      audio = new Audio();
      audio.addEventListener('ended', () => setPlayingId(null));
      audioRef.current = audio;
    }
    if (playingId === id) {
      audio.pause();
      setPlayingId(null);
      return;
    }
    audio.src = url;
    audio.currentTime = 0;
    void audio.play().catch(() => setPlayingId(null));
    setPlayingId(id);
  };

  return (
    <div className="mt-8 flex w-full max-w-md flex-col gap-2">
      {presetVoices.map((voice) => {
        const isSelected = selection === voice.id;
        const isPlaying = playingId === voice.id;
        return (
          <div
            key={voice.id}
            role="radio"
            aria-checked={isSelected}
            tabIndex={0}
            onClick={() => onSelectionChange(voice.id)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelectionChange(voice.id);
              }
            }}
            className={cn(
              'flex cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors',
              'focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
              isSelected
                ? 'border-primary bg-primary/5 ring-primary/40 ring-1'
                : 'border-border hover:border-foreground/30 hover:bg-muted/40'
            )}
          >
            <button
              type="button"
              aria-label={
                isPlaying ? strings.stopPreview(voice.name) : strings.previewVoice(voice.name)
              }
              onClick={(e) => {
                e.stopPropagation();
                togglePreview(voice.id, voice.sampleUrl);
              }}
              className={cn(
                'flex size-9 shrink-0 items-center justify-center rounded-full border transition-colors',
                isPlaying
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border text-foreground/70 hover:bg-muted'
              )}
            >
              {isPlaying ? (
                <PauseIcon weight="fill" className="size-4" />
              ) : (
                <PlayIcon weight="fill" className="size-4" />
              )}
            </button>
            <span className="flex flex-col">
              <span className="text-foreground text-sm font-medium">{voice.name}</span>
              <span className="text-muted-foreground text-xs">{voice.descriptor}</span>
            </span>
            <span
              className={cn(
                'ml-auto size-2.5 rounded-full transition-colors',
                isSelected ? 'bg-primary' : 'bg-transparent'
              )}
              aria-hidden="true"
            />
          </div>
        );
      })}

      <div className="my-1 flex items-center gap-3">
        <span className="bg-border h-px flex-1" />
        <span className="text-muted-foreground text-xs">{strings.orDivider}</span>
        <span className="bg-border h-px flex-1" />
      </div>

      <div
        role="radio"
        aria-checked={selection === CLONE_SELECTION}
        tabIndex={0}
        onClick={() => onSelectionChange(CLONE_SELECTION)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelectionChange(CLONE_SELECTION);
          }
        }}
        className={cn(
          'flex cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors',
          'focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
          selection === CLONE_SELECTION
            ? 'border-primary bg-primary/5 ring-primary/40 ring-1'
            : 'border-border hover:border-foreground/30 hover:bg-muted/40'
        )}
      >
        <span className="border-border text-foreground/70 flex size-9 shrink-0 items-center justify-center rounded-full border">
          <MicrophoneIcon weight="fill" className="size-4" />
        </span>
        <span className="flex flex-col">
          <span className="text-foreground text-sm font-medium">{strings.cloneTitle}</span>
          <span className="text-muted-foreground text-xs">{strings.cloneSubtitle}</span>
        </span>
        <span
          className={cn(
            'ml-auto size-2.5 rounded-full transition-colors',
            selection === CLONE_SELECTION ? 'bg-primary' : 'bg-transparent'
          )}
          aria-hidden="true"
        />
      </div>

      <div
        role="radio"
        aria-checked={selection === DESIGN_SELECTION}
        tabIndex={0}
        onClick={() => onSelectionChange(DESIGN_SELECTION)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelectionChange(DESIGN_SELECTION);
          }
        }}
        className={cn(
          'flex cursor-pointer flex-col rounded-xl border px-4 py-3 text-left transition-colors',
          'focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
          selection === DESIGN_SELECTION
            ? 'border-primary bg-primary/5 ring-primary/40 ring-1'
            : 'border-border hover:border-foreground/30 hover:bg-muted/40'
        )}
      >
        <div className="flex items-center gap-3">
          <span className="border-border text-foreground/70 flex size-9 shrink-0 items-center justify-center rounded-full border">
            <SparkleIcon weight="fill" className="size-4" />
          </span>
          <span className="flex flex-col">
            <span className="text-foreground text-sm font-medium">{strings.designTitle}</span>
            <span className="text-muted-foreground text-xs">{strings.designSubtitle}</span>
          </span>
          <span
            className={cn(
              'ml-auto size-2.5 rounded-full transition-colors',
              selection === DESIGN_SELECTION ? 'bg-primary' : 'bg-transparent'
            )}
            aria-hidden="true"
          />
        </div>
        {selection === DESIGN_SELECTION && (
          <textarea
            autoFocus
            value={designInstruction}
            onChange={(e) => onDesignInstructionChange(e.target.value)}
            // The parent card is the radio: don't let clicks/keys inside the
            // textarea re-trigger its select handlers (space/enter must type).
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            rows={2}
            maxLength={500}
            placeholder={strings.designPlaceholder}
            className={cn(
              'border-border bg-background placeholder:text-muted-foreground/60 mt-3 w-full resize-none rounded-lg border px-3 py-2 text-sm',
              'focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none'
            )}
          />
        )}
      </div>
    </div>
  );
}
