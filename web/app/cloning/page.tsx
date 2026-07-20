import { headers } from 'next/headers';
import { CLONE_SELECTION } from '@/app-config';
import { App } from '@/components/app/app';
import { getAppConfig } from '@/lib/utils';

// Focused voice-cloning entry point: same app as /, but with the clone option
// preselected and a persistent Fish Audio header across the whole session.
export default async function Page() {
  const hdrs = await headers();
  const appConfig = await getAppConfig(hdrs);

  return (
    <App
      appConfig={appConfig}
      headerTitle="Fish Audio Realtime Voice Cloning"
      initialSelection={CLONE_SELECTION}
    />
  );
}
