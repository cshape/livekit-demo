# Voice cloning demo — frontend

The web half of the [voice cloning demo](../README.md): a Next.js 15 app that
mints LiveKit room tokens and renders the call UI. It's built on
[Agents UI](https://livekit.io/ui) components + the
[LiveKit JS SDK](https://github.com/livekit/client-sdk-js), bootstrapped from
[`agent-starter-react`](https://github.com/livekit-examples/agent-starter-react).

This directory is self-contained — you can run it on its own against any
LiveKit project that has the [`fish/`](../fish/) agent (or any compatible agent)
connected to it.

## Run it standalone

You need a [LiveKit Cloud](https://cloud.livekit.io) project and an agent
running against it (see [`fish/README.md`](../fish/README.md)).

```bash
cp .env.example .env.local   # then fill in your LiveKit credentials
pnpm install
pnpm dev                     # http://localhost:3000
```

### Docker

```bash
docker build -t voice-clone-web .
docker run --rm -p 3000:3000 --env-file .env.local voice-clone-web
```

The image is built from Next's standalone output (`output: 'standalone'` in
[`next.config.ts`](./next.config.ts)) so it ships just the server + traced
dependencies.

## Environment variables

Server-side only (used by the `/api/token` route to mint access tokens):

```env
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

# Optional. Leave blank for automatic agent dispatch; set a name for explicit
# dispatch (https://docs.livekit.io/agents/server/agent-dispatch).
AGENT_NAME=
```

## Customizing

- Landing copy and the privacy note live in [`components/app/welcome-view.tsx`](./components/app/welcome-view.tsx).
- Branding, page metadata, and visualizer presets live in [`app-config.ts`](./app-config.ts).
- The clone-status pill is [`components/app/clone-status-banner.tsx`](./components/app/clone-status-banner.tsx), driven by the agent's `clone.state` participant attribute.

For the full Agents UI component reference (visualizer styles, updating
components via `pnpm shadcn:install`, etc.), see the upstream
[`agent-starter-react`](https://github.com/livekit-examples/agent-starter-react) README.
