import { useCallback, useEffect, useRef, useState } from 'react';
import { useAppStore } from '../store';
import { apiJson } from '../api/client';
import { installRecommendedAsr } from '../utils/asrModelMissing';

// Keep model checks separate from microphone access: checking the page must
// never record audio or start a download. Capture still validates server-side.
export function useDictationReadiness() {
  const modelId = useAppStore((store) => store.dictationModelId);
  const [state, setState] = useState({ phase: 'checking', missing: null });
  const task = useRef(null);
  const mounted = useRef(false);
  const checking = useRef(false);
  const check = useCallback(async () => {
    if (task.current || checking.current) return false;
    checking.current = true;
    try {
      const result = await apiJson(
        `/dictation/readiness?model_id=${encodeURIComponent(useAppStore.getState().dictationModelId || '')}`,
      );
      if (mounted.current && !task.current)
        setState((previous) => ({
          phase: result.ready === true ? 'ready' : result.missing ? 'missing' : 'error',
          missing: result.missing,
          error: result.ready !== true && previous.error,
        }));
      return result.ready === true;
    } catch {
      if (mounted.current && !task.current) setState({ phase: 'error', missing: null });
      return false;
    } finally {
      checking.current = false;
    }
  }, [modelId]);
  useEffect(() => {
    mounted.current = true;
    void check();
    const refresh = () => {
      if (document.visibilityState !== 'hidden') void check();
    };
    const timer = setInterval(refresh, 5000);
    window.addEventListener('focus', refresh);
    return () => {
      mounted.current = false;
      clearInterval(timer);
      window.removeEventListener('focus', refresh);
      task.current?.abort();
    };
  }, [check]);

  const install = useCallback(async () => {
    if (task.current || !state.missing?.recommended?.repo_id) return;
    const controller = new AbortController();
    task.current = controller;
    setState((previous) => ({ ...previous, phase: 'installing', percent: 0, error: false }));
    try {
      const installed = await installRecommendedAsr(state.missing, {
        signal: controller.signal,
        onProgress: ({ percent }) => {
          if (mounted.current) setState((previous) => ({ ...previous, percent }));
        },
      });
      task.current = null;
      if (installed?.dictation_id && mounted.current) {
        // The installer persisted this selection; keep the recorder's store
        // in sync before the next readiness check and capture request.
        useAppStore.setState({ dictationModelId: installed.dictation_id });
      }
      if (mounted.current) await check();
    } catch {
      if (mounted.current) setState((previous) => ({ ...previous, phase: 'missing', error: true }));
    } finally {
      task.current = null;
    }
  }, [state.missing, check]);
  return { ...state, check, install };
}
