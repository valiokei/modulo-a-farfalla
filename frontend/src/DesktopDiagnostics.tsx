import {useEffect, useState} from 'react';
import {Download, Settings2} from 'lucide-react';
import {t} from './i18n';

type Profile = 'production' | 'simple' | 'diagnostic';

export function DesktopDiagnostics() {
  const [profile, setProfile] = useState<Profile>('production');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/desktop/diagnostics/profile').then(response => response.json())
      .then(data => setProfile(data.profile)).catch(() => setError(t('diagnostics_unavailable')));
  }, []);

  async function changeProfile(next: Profile) {
    setBusy(true); setError('');
    try {
      const response = await fetch('/desktop/diagnostics/profile', {
        method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({profile: next})
      });
      if (!response.ok) throw new Error();
      setProfile(next);
    } catch {setError(t('diagnostics_unavailable'));}
    finally {setBusy(false);}
  }

  async function exportDiagnostics() {
    setBusy(true); setError('');
    try {
      const response = await fetch('/desktop/diagnostics/export', {method: 'POST'});
      if (!response.ok) throw new Error();
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'modulo-a-farfalla-diagnostics.zip'; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {setError(t('diagnostics_unavailable'));}
    finally {setBusy(false);}
  }

  return <details className="desktopDiagnostics">
    <summary><Settings2 size={16}/>{t('diagnostics_title')}</summary>
    <div className="desktopDiagnosticsControls">
      <label>{t('diagnostics_level')}
        <select value={profile} disabled={busy} onChange={event => void changeProfile(event.target.value as Profile)}>
          <option value="production">{t('diagnostics_production')}</option>
          <option value="simple">{t('diagnostics_simple')}</option>
          <option value="diagnostic">{t('diagnostics_detailed')}</option>
        </select>
      </label>
      <button type="button" disabled={busy} onClick={() => void exportDiagnostics()}>
        <Download size={16}/>{t('diagnostics_export')}
      </button>
    </div>
    {error && <p role="alert">{error}</p>}
  </details>;
}
