import { ShieldCheckIcon } from '@phosphor-icons/react/dist/ssr';
import { Button } from '@/components/ui/button';

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: () => void;
}

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  return (
    <div ref={ref}>
      <section className="bg-background mx-auto flex max-w-prose flex-col items-center justify-center px-6 text-center">
        <h1 className="text-foreground text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
          Clone your voice with Fish Audio
        </h1>

        <p className="text-muted-foreground mt-4 text-base leading-relaxed text-pretty md:text-lg">
          Have a quick chat with the voice agent. If you&rsquo;d like, it can clone your voice from
          about ten seconds of the conversation and start talking back to you in it &mdash; totally
          your call.
        </p>

        <p className="text-muted-foreground/80 mt-4 flex items-center gap-2 text-sm">
          <ShieldCheckIcon weight="bold" className="size-4 shrink-0" aria-hidden="true" />
          Your recording and the cloned voice are deleted the moment the call ends.
        </p>

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
