import { headers } from 'next/headers';
import { localizeAppConfig } from '@/app-config';
import { App } from '@/components/app/app';
import { getAppConfig } from '@/lib/utils';

// Japanese version of the demo: same app, fully localized. The `locale` prop
// switches the UI strings + preset voices, and rides the agent metadata as
// {"lang":"ja"} so the worker localizes its prompts, voices, and STT too.
export default async function Page() {
  const hdrs = await headers();
  const appConfig = localizeAppConfig(await getAppConfig(hdrs), 'ja');

  return <App appConfig={appConfig} locale="ja" />;
}
