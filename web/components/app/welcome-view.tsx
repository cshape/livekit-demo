import { VoicePicker } from '@/components/app/voice-picker';
import { Button } from '@/components/ui/button';

interface WelcomeViewProps {
  startButtonText: string;
  selection: string;
  onSelectionChange: (selection: string) => void;
  onStartCall: () => void;
}

export const WelcomeView = ({
  startButtonText,
  selection,
  onSelectionChange,
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  return (
    <div ref={ref}>
      <section className="bg-background mx-auto flex max-w-prose flex-col items-center justify-center px-6 py-10 text-center">
        <h1 className="text-foreground text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
          Hear LiveKit&rsquo;s expressive mode
        </h1>

        <p className="text-muted-foreground mt-4 max-w-prose text-base leading-relaxed text-pretty md:text-lg">
          A LiveKit voice agent running Fish Audio&rsquo;s expressive text-to-speech. Flip it
          between <span className="text-foreground font-medium">casual</span> and{' '}
          <span className="text-foreground font-medium">professional</span> mid-call and watch its
          mood shift in real time. Pick a voice to start, or clone your own.
        </p>

        <VoicePicker selection={selection} onSelectionChange={onSelectionChange} />

        <Button
          size="lg"
          onClick={onStartCall}
          className="mt-8 w-64 rounded-full font-mono text-xs font-bold tracking-wider uppercase"
        >
          {startButtonText}
        </Button>
      </section>
    </div>
  );
};
