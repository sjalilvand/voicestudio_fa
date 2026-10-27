/**
 * Settings → Network.
 *
 * Proxy only. The FFmpeg-path override that used to share this panel moved to
 * Settings → Audio tools (same backend store — prefs `env.FFMPEG_PATH` via
 * `/media-tools` — richer controls: version, origin, restore bundled); a
 * pointer row below deep-links there so muscle memory still lands.
 */
import React, { useEffect, useState } from 'react';
import { toast } from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import { Wifi, Globe, Film } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useAppStore } from '../../store';
import { useSystemInfo, queryKeys } from '../../api/hooks';
import { Button, Badge } from '../../ui';
import { SettingsSection, SettingRow, SettingsInput } from './primitives';
import RestartBadge from './RestartBadge';

// CLEAN-ROOM (spec W7-frontend §1): default-exported NetworkTab component (proxy field with save/clear, FFmpeg pointer row) goes here.
