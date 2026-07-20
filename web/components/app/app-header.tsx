import { FishAudioLogo } from '@/components/app/fish-audio-logo';

// Branded header shown during the in-call cloning workflow: logo top-left,
// title right. Fixed at the top with z-50 so it overlays the in-call view
// (which is fixed inset-0). The inner band matches the chat body width
// (max-w-2xl); on narrow/mobile widths the title wraps to two or three lines.
export function AppHeader({ title }: { title: string }) {
  return (
    <header className="bg-background fixed inset-x-0 top-0 z-50 flex min-h-16 items-center pt-4 md:pt-6">
      <div className="mx-auto flex w-full max-w-2xl items-center justify-between gap-3 px-4 py-3 md:px-6">
        <FishAudioLogo className="w-12 shrink-0 md:w-16" />
        <div className="text-foreground text-right text-base leading-tight font-semibold tracking-tight text-balance md:text-2xl lg:text-3xl">
          {title}
        </div>
      </div>
    </header>
  );
}
