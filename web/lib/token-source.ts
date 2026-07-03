import { TokenSource } from 'livekit-client';
import type { TokenSourceFetchOptions, TokenSourceResponseObject } from 'livekit-client';

// /api/token mints 15-minute tokens; treat cached ones as fresh well inside that.
const TOKEN_MAX_AGE_MS = 10 * 60 * 1000;

// Prefetch cache shared across token-source instances. app.tsx recreates the token
// source whenever the selection metadata changes (to dodge livekit-client's inverted
// TokenSourceCached check — see the comment there), so per-instance caching would
// never survive to the actual start() call; this module-level cache does. Keyed by
// the fetch options that affect the minted token.
const tokenCache = new Map<string, { response: TokenSourceResponseObject; fetchedAt: number }>();

/**
 * Drop all prefetched tokens. Called once a session actually connects: a consumed
 * token pins the room name, and reusing it for a later call could re-join a room
 * whose previous agent job is still shutting down.
 */
export function clearTokenCache() {
  tokenCache.clear();
}

async function mintToken(options: TokenSourceFetchOptions): Promise<TokenSourceResponseObject> {
  // Same wire format TokenSource.endpoint() produces for our /api/token route.
  const roomConfig =
    options.agentName || options.agentMetadata
      ? {
          agents: [
            {
              ...(options.agentName ? { agent_name: options.agentName } : {}),
              ...(options.agentMetadata ? { metadata: options.agentMetadata } : {}),
            },
          ],
        }
      : undefined;

  const res = await fetch('/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ room_config: roomConfig }),
  });
  if (!res.ok) {
    throw new Error(`Error generating token: received ${res.status} / ${await res.text()}`);
  }
  return (await res.json()) as TokenSourceResponseObject;
}

/**
 * Token source for /api/token with an app-level prefetch cache, so a token minted
 * by `session.prepareConnection()` on the landing page is actually reused when the
 * user clicks start. (livekit-client's own TokenSourceCached can't provide this:
 * its cache check is inverted, so a fetch with MATCHING options always re-fetches —
 * that re-fetch lands here and hits this cache instead of the network.)
 */
export function createCachingTokenSource() {
  return TokenSource.custom(async (options) => {
    const key = JSON.stringify([options.agentName ?? '', options.agentMetadata ?? '']);
    const hit = tokenCache.get(key);
    if (hit && Date.now() - hit.fetchedAt < TOKEN_MAX_AGE_MS) {
      return hit.response;
    }
    const response = await mintToken(options);
    tokenCache.set(key, { response, fetchedAt: Date.now() });
    return response;
  });
}
