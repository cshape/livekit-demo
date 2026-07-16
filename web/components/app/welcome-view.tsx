import { DESIGN_SELECTION } from '@/app-config';
import { VoicePicker } from '@/components/app/voice-picker';
import { Button } from '@/components/ui/button';
import { useStrings } from '@/lib/i18n';

interface WelcomeViewProps {
  startButtonText: string;
  selection: string;
  onSelectionChange: (selection: string) => void;
  designInstruction: string;
  onDesignInstructionChange: (value: string) => void;
  onStartCall: () => void;
}

export const WelcomeView = ({
  startButtonText,
  selection,
  onSelectionChange,
  designInstruction,
  onDesignInstructionChange,
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  const strings = useStrings();
  // Designing a voice needs a description to design from.
  const startDisabled = selection === DESIGN_SELECTION && designInstruction.trim().length === 0;

  return (
    <div ref={ref}>
      <section className="bg-background mx-auto flex max-w-prose flex-col items-center justify-center px-6 py-10 text-center">
        <h1 className="text-foreground text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
          {strings.welcomeHeading}
        </h1>

        <p className="text-muted-foreground mt-4 max-w-prose text-base leading-relaxed text-pretty md:text-lg">
          {strings.descIntro}
          <span className="text-foreground font-medium">{strings.descCasual}</span>
          {strings.descMid}
          <span className="text-foreground font-medium">{strings.descProfessional}</span>
          {strings.descTail}
        </p>

        <VoicePicker
          selection={selection}
          onSelectionChange={onSelectionChange}
          designInstruction={designInstruction}
          onDesignInstructionChange={onDesignInstructionChange}
        />

        <Button
          size="lg"
          onClick={onStartCall}
          disabled={startDisabled}
          className="mt-8 w-64 rounded-full font-mono text-xs font-bold tracking-wider uppercase"
        >
          {startButtonText}
        </Button>
      </section>
    </div>
  );
};
