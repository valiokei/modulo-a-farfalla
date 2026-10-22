import {useEffect, useState, type ReactNode} from 'react';
import {AlertTriangle, Download, RefreshCw, Sparkles} from 'lucide-react';
import {t, useI18n} from './i18n';
import './desktop.css';

export const isDesktop = import.meta.env.VITE_DESKTOP === 'true';

type AiStatus = {phase?: string; supported?: boolean; active?: boolean; progress?: number};
type UpdateState = {update_available?: boolean; latest_version?: string};

/**
 * One-line strip shown above the app only when something needs attention
 * (backend unreachable, update available, AI runtime installing or waiting for a
 * restart). Everything else — encoder, versions, diagnostics, AI install — lives
 * in Settings, so the strip takes no space in normal use.
 */
export function DesktopStatus({openSettings}: {openSettings?: () => void}) {
  useI18n();
  const [ai, setAi] = useState<AiStatus>();
  const [update, setUpdate] = useState<UpdateState>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!isDesktop) return;
    document.body.classList.add('desktop-app');
    return () => document.body.classList.remove('desktop-app');
  }, []);
  useEffect(() => {
    if (!isDesktop) return;
    let stopped = false;
    const poll = async () => {
      try {
        const response = await fetch('/desktop/health', {cache: 'no-store'});
        if (!response.ok) throw new Error('health');
        const health = await response.json();
        if (!stopped) {setAi(health.ai); setFailed(false);}
      } catch {if (!stopped) setFailed(true);}
    };
    const checkUpdate = () => fetch('/desktop/update/check', {cache: 'no-store'}).then((r) => r.ok ? r.json() : undefined)
      .then((body) => {if (!stopped && body) setUpdate(body);}).catch(() => undefined);
    void poll(); void checkUpdate();
    const timer = setInterval(poll, 5000);
    const updateTimer = setInterval(checkUpdate, 12 * 60 * 60 * 1000);
    return () => {stopped = true; clearInterval(timer); clearInterval(updateTimer);};
  }, []);
  if (!isDesktop) return null;
  const installing = ['starting', 'downloading', 'verifying', 'extracting'].includes(ai?.phase || '');
  let body: ReactNode = null, tone = '';
  if (failed) body = <><AlertTriangle size={16}/>{t('status_backend_unreachable')}</>;
  else if (installing) {tone = 'busy'; body = <><Download size={16}/>{t('desktop_ai_downloading')}<progress value={ai?.progress || 0} max="100"/>{ai?.progress || 0}%</>;}
  else if (ai?.phase === 'ready' && !ai.active) {tone = 'busy'; body = <><RefreshCw size={16}/>{t('desktop_ai_restart_short')}</>;}
  else if (update?.update_available) body = <><Sparkles size={16}/>{t('desktop_update_available')}: {update.latest_version}</>;
  if (!body) return null;
  return <aside className={`statusStrip ${tone}`} role="status" aria-live="polite">{body}
    {openSettings && <button type="button" onClick={openSettings}>{t('settings_open')}</button>}</aside>;
}
