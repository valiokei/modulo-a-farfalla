import {useEffect, useState} from 'react';
import {Download, ExternalLink, RefreshCw, ShieldCheck} from 'lucide-react';
import {t, useI18n} from './i18n';

const isDesktop = import.meta.env.VITE_DESKTOP === 'true';

type UpdateState = {current_version?: string; latest_version?: string;
  update_available?: boolean; release_url?: string; name?: string; install_supported?: boolean};

export function DesktopUpdate() {
  useI18n();
  const [state, setState] = useState<UpdateState>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const check = async (quiet = false) => {
    if (!quiet) {setBusy(true); setMessage('');}
    try {
      const result = await fetch('/desktop/update/check', {cache: 'no-store'}).then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.code && ['dns','tls','proxy','timeout','http','network','metadata','asset'].includes(body.code)
          ? t(`desktop_update_${body.code}`) : body.detail || t('desktop_update_error'));
        return body;
      });
      setState(result);
    } catch (error) {
      setMessage((error as Error).message || t('desktop_update_error'));
    } finally {if (!quiet) setBusy(false);}
  };

  useEffect(() => {
    if (!isDesktop) return;
    void check(true);
    const timer = window.setInterval(() => void check(true), 12 * 60 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!isDesktop) return null;

  const install = async () => {
    if (!window.confirm(t('desktop_update_confirm'))) return;
    setBusy(true); setMessage(t('desktop_update_downloading'));
    try {
      const response = await fetch('/desktop/update/install', {method: 'POST'});
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || t('desktop_update_error'));
      setMessage(t('desktop_update_restarting'));
    } catch (error) {setMessage((error as Error).message || t('desktop_update_error')); setBusy(false);}
  };

  return <section className={`desktopUpdate ${state?.update_available ? 'available' : ''}`} aria-live="polite">
    <div className="desktopUpdateHead"><div><ShieldCheck size={18}/><b>{t('desktop_update_title')}</b>
      {state?.current_version && <small>{t('desktop_update_current')}: {state.current_version}</small>}
      <small>{t('desktop_update_public')}</small></div>
      {state?.update_available && <strong>{t('desktop_update_available')}: {state.latest_version}</strong>}</div>
    <div className="desktopUpdateActions"><span>{message || (state?.update_available ? state.name : state?.latest_version ? t('desktop_update_current_ok') : t('desktop_update_not_checked'))}</span>
      {state?.update_available ? (state.install_supported === false
        ? <a className="desktopUpdateInstall" href={state.release_url || 'https://github.com/valiokei/modulo-a-farfalla/releases'} target="_blank" rel="noreferrer"><Download size={16}/>{t('desktop_update_install_manual')}</a>
        : <button type="button" disabled={busy} onClick={() => void install()}><Download size={16}/>{t('desktop_update_install')}</button>)
        : <button type="button" disabled={busy} onClick={() => void check()}><RefreshCw size={16}/>{busy ? t('desktop_update_checking') : message ? t('desktop_update_retry') : t('desktop_update_check')}</button>}
      <a href={state?.release_url || 'https://github.com/valiokei/modulo-a-farfalla/releases'} target="_blank" rel="noreferrer"><ExternalLink size={15}/>{t('desktop_update_release')}</a>
    </div>
    {message && <p className="desktopUpdateMessage" role="alert">{message}</p>}
  </section>;
}
