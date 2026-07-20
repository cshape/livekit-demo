import { FishAudioLogo } from '@/components/app/fish-audio-logo';

// Persistent branded header: logo top-left, title right. Sticky and in-flow so
// the welcome view lays out below it; z-50 keeps it above the in-call view
// (which is fixed inset-0) for the whole conversation.
export function AppHeader({ title }: { title: string }) {
  return (
    <header className="bg-background sticky top-0 z-50 flex h-16 items-center justify-between gap-4 px-4 md:px-6">
      <FishAudioLogo className="w-14 shrink-0 md:w-16" />
      <div className="text-foreground text-right text-lg leading-tight font-semibold tracking-tight md:text-2xl lg:text-3xl">
        {title}
      </div>
    </header>
  );
}
