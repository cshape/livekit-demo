import { headers } from 'next/headers';
import { ImageResponse } from 'next/og';
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { getAppConfig } from '@/lib/utils';

// Image metadata
export const alt = "Fish Audio expressive voice demo";
export const size = {
  width: 1200,
  height: 628,
};

function isRemoteFile(uri: string) {
  return uri.startsWith('http');
}

function doesLocalFileExist(uri: string) {
  return existsSync(join(process.cwd(), uri));
}

// LOCAL FILES MUST BE IN PUBLIC FOLDER
async function loadFileData(filePath: string): Promise<ArrayBuffer> {
  if (isRemoteFile(filePath)) {
    const response = await fetch(filePath);
    if (!response.ok) {
      throw new Error(`Failed to fetch ${filePath} - ${response.status} ${response.statusText}`);
    }
    return await response.arrayBuffer();
  }

  // Try file system first (works in local development)
  if (doesLocalFileExist(filePath)) {
    const buffer = await readFile(join(process.cwd(), filePath));
    return buffer.buffer.slice(
      buffer.byteOffset,
      buffer.byteOffset + buffer.byteLength
    ) as ArrayBuffer;
  }

  // Fallback to fetching from public URL (works in production)
  const publicFilePath = filePath.replace('public/', '');
  const fontUrl = `https://${process.env.VERCEL_URL}/${publicFilePath}`;

  const response = await fetch(fontUrl);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${fontUrl} - ${response.status} ${response.statusText}`);
  }

  return await response.arrayBuffer();
}

export const contentType = 'image/png';

// Waveform bar heights (px) — a stylized "expressive voice" mark.
const WAVEFORM_BARS = [36, 84, 148, 108, 64];

// Image generation
export default async function Image() {
  const hdrs = await headers();
  const appConfig = await getAppConfig(hdrs);

  // Load fonts - use file system in dev, fetch in production
  let commitMonoData: ArrayBuffer | undefined;
  let everettLightData: ArrayBuffer | undefined;

  try {
    commitMonoData = await loadFileData('public/commit-mono-400-regular.woff');
    everettLightData = await loadFileData('public/everett-light.woff');
  } catch (e) {
    console.error('Failed to load fonts:', e);
    // Continue without custom fonts - will fall back to system fonts
  }

  return new ImageResponse(
    (
      // ImageResponse JSX element
      <div
        style={{
          display: 'flex',
          width: size.width,
          height: size.height,
          backgroundColor: '#0A0A0A',
          backgroundImage: 'radial-gradient(circle at 75% 40%, #1c1c1c 0%, #0A0A0A 60%)',
        }}
      >
        {/* wordmark */}
        <div
          style={{
            position: 'absolute',
            top: 40,
            left: 48,
            fontSize: 28,
            fontFamily: 'Everett',
            color: 'white',
            letterSpacing: 0.5,
          }}
        >
          {appConfig.companyName}
        </div>
        {/* waveform mark */}
        <div
          style={{
            position: 'absolute',
            top: 160,
            right: 140,
            height: 160,
            display: 'flex',
            alignItems: 'center',
            gap: 18,
          }}
        >
          {WAVEFORM_BARS.map((h, i) => (
            <div
              key={i}
              style={{
                width: 34,
                height: h,
                borderRadius: 17,
                backgroundColor: 'white',
              }}
            />
          ))}
        </div>
        {/* title */}
        <div
          style={{
            position: 'absolute',
            bottom: 90,
            left: 48,
            width: '560px',
            display: 'flex',
            flexDirection: 'column',
            gap: 20,
          }}
        >
          <div
            style={{
              alignSelf: 'flex-start',
              backgroundColor: '#1F1F1F',
              padding: '2px 10px',
              borderRadius: 4,
              fontSize: 13,
              fontFamily: 'CommitMono',
              fontWeight: 600,
              color: '#999999',
              letterSpacing: 1.2,
            }}
          >
            EXPRESSIVE VOICE DEMO
          </div>
          <div
            style={{
              fontSize: 52,
              fontWeight: 300,
              fontFamily: 'Everett',
              color: 'white',
              lineHeight: 1.1,
            }}
          >
            Talk to an expressive voice agent
          </div>
        </div>
      </div>
    ),
    // ImageResponse options
    {
      // For convenience, we can re-use the exported opengraph-image
      // size config to also set the ImageResponse's width and height.
      ...size,
      fonts: [
        ...(commitMonoData
          ? [
              {
                name: 'CommitMono',
                data: commitMonoData,
                style: 'normal' as const,
                weight: 400 as const,
              },
            ]
          : []),
        ...(everettLightData
          ? [
              {
                name: 'Everett',
                data: everettLightData,
                style: 'normal' as const,
                weight: 300 as const,
              },
            ]
          : []),
      ],
    }
  );
}
