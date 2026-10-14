import assert from 'node:assert/strict';
import test from 'node:test';

import metadata from '../../store/metadata.json' with { type: 'json' };
import {
  validateTemplateArchiveEntries,
  verifySnapRuntimePayload,
} from '../snap-template-payload.mjs';
import { verifySnapMetadata } from '../../scripts/verify_snap_artifact.mjs';

const snapYaml = `base: core22
grade: stable
confinement: strict
name: voicestudio
version: 0.5.7
title: VoiceStudio
summary: ${metadata.listing.shortDescription}
description: ${metadata.listing.description}
apps:
  voicestudio:
    plugs:
      - browser-support
      - desktop
      - desktop-legacy
      - home
      - x11
      - wayland
      - unity7
      - network
      - network-bind
      - gsettings
      - audio-playback
      - audio-record
      - pulseaudio
      - opengl
`;

test('accepts canonical strict Snap metadata', () => {
  assert.deepEqual(verifySnapMetadata(snapYaml, { ...metadata, version: '0.5.7' }), {
    name: 'voicestudio',
    version: '0.5.7',
    confinement: 'strict',
    base: 'core22',
    plugs: [
      'browser-support',
      'desktop',
      'desktop-legacy',
      'home',
      'x11',
      'wayland',
      'unity7',
      'network',
      'network-bind',
      'gsettings',
      'audio-playback',
      'audio-record',
      'pulseaudio',
      'opengl',
    ],
  });
});

test('rejects weakened confinement, missing capabilities and broad removable access', () => {
  const expected = { ...metadata, version: '0.5.7' };
  assert.throws(() => verifySnapMetadata(snapYaml.replace('strict', 'classic'), expected));
  assert.throws(() => verifySnapMetadata(snapYaml.replace('      - audio-record\n', ''), expected));
  assert.throws(() => verifySnapMetadata(`${snapYaml}      - removable-media\n`, expected));
});

const runtimeListing = `
squashfs-root/desktop-init.sh
squashfs-root/desktop-common.sh
squashfs-root/desktop-gnome-specific.sh
squashfs-root/usr/lib/x86_64-linux-gnu/libnss3.so
`;

test('requires an expanded desktop runtime in the Snap payload', () => {
  assert.doesNotThrow(() => verifySnapRuntimePayload(runtimeListing));
  assert.throws(
    () => verifySnapRuntimePayload(runtimeListing.replace('squashfs-root/desktop-init.sh\n', '')),
    /desktop-init\.sh/,
  );
  assert.throws(
    () =>
      verifySnapRuntimePayload(
        `${runtimeListing}squashfs-root/snap-template-electron-4.0-2-amd64.tar\n`,
      ),
    /unexpanded desktop runtime/,
  );
});

test('rejects unsafe or incomplete nested template archives', () => {
  const entries = `./\n${runtimeListing.replaceAll('squashfs-root/', './')}`;
  assert.doesNotThrow(() => validateTemplateArchiveEntries(entries));
  assert.throws(() => validateTemplateArchiveEntries(`${entries}../escape\n`), /Unsafe/);
  assert.throws(
    () => validateTemplateArchiveEntries(entries.replace('./desktop-init.sh\n', '')),
    /desktop-init\.sh/,
  );
});
