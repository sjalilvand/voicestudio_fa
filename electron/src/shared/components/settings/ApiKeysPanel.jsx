/**
 * Settings → API Keys panel (Wave 2 AUTH-03 UI half).
 *
 * Consumes the Wave 1 resolver state endpoint at
 *   GET    /api/settings/hf-token/state
 *   POST   /api/settings/hf-token
 *   DELETE /api/settings/hf-token?also_clear_hf_cli={bool}
 *
 * Renders one row per source (App / Env / HF CLI) with set/unset indicator,
 * masked token preview, whoami username + green check on success, and an
 * "Active" badge on whichever row is currently serving the cascade.
 *
 * Threat T-02-02: the panel never displays the full token. The masked
 * value comes from the resolver state endpoint; the full token only
 * crosses the IPC boundary on Save (POST) and is cleared from local
 * state on success.
 *
 * Note: the GET + POST go through `apiJson` / `apiPost` from
 * `../../api/client` (the canonical base-URL site). The DELETE uses raw
 * fetch with the same `API` base so query params can be appended cleanly.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, KeyRound, RefreshCw, Save, Trash2, XCircle } from 'lucide-react';
import { apiJson, apiPost, apiFetch, API } from '../../api/client';
import { SettingsSection, InfoHint } from './primitives';

// CLEAN-ROOM (spec W11-residue §E11): default-exported ApiKeysPanel component (HF token sources, save, clear)
