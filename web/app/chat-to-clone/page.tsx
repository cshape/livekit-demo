import { headers } from 'next/headers';
import { App } from '@/components/app/app';
import { getAppConfig } from '@/lib/utils';

// Conversational voice-cloning entry point: same app as /, but with no scripted
// read. The user just talks; once ~10s of their voice is captured the agent clones
// them mid-conversation and switches into their voice. A persistent Fish Audio
// header rides the whole in-call session. Sends `{chatClone:true}` agent metadata.
export default async function Page() {
  const hdrs = await headers();
  const appConfig = await getAppConfig(hdrs);

  return (
    <App appConfig={appConfig} headerTitle="Fish Audio Conversational Voice Cloning" chatClone />
  );
}
