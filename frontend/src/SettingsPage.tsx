import {useEffect, useState, type ReactNode} from 'react';
import {Cpu, Database, Languages, MonitorPlay, Moon, Palette, ShieldCheck, Sparkles, Stethoscope, Sun, SunMoon} from 'lucide-react';
import {getLang, setLang, t, useI18n} from './i18n';
import {setThemeChoice, useTheme, type ThemeChoice} from './theme';
import {DesktopAIInstaller} from './DesktopAI';
import {DesktopUpdate} from './DesktopUpdate';
import {DesktopDiagnostics} from './DesktopDiagnostics';
import {isDesktop} from './DesktopStatus';
import './settings.css';

type Health = {video?: {selected?: string; last_operation?: {encoder: string; decoder: string; fallback: boolean}}; data_root?: string; version?: string};
const vendor = (value?: string) => value === 'cpu' ? 'CPU' : value?.toUpperCase() || '—';

export function SettingsPage() {
  useI18n();
  const {choice} = useTheme();
  const [health, setHealth] = useState<Health>();
  useEffect(() => {
    if (!isDesktop) return;
    fetch('/desktop/health', {cache: 'no-store'}).then((r) => r.json()).then(setHealth).catch(() => undefined);
  }, []);
  const themes: [ThemeChoice, string, ReactNode][] = [['light', t('theme_light'), <Sun size={16}/>], ['dark', t('theme_dark'), <Moon size={16}/>], ['system', t('theme_system'), <SunMoon size={16}/>]];
  return <main className="library settingsPage">
    <div className="libraryTop"><div><p className="eyebrow">{t('settings_eyebrow')}</p><h1>{t('settings_title')}</h1><p>{t('settings_subtitle')}</p></div></div>
    <section className="settingsCard" aria-labelledby="set-look"><h2 id="set-look"><Palette size={18}/>{t('settings_appearance')}</h2>
      <div className="settingsRow"><span><b>{t('theme_label')}</b><small>{t('theme_hint')}</small></span>
        <div className="segmented" role="radiogroup" aria-label={t('theme_label')}>{themes.map(([value, text, icon]) =>
          <button key={value} role="radio" aria-checked={choice === value} className={choice === value ? 'active' : ''} onClick={() => setThemeChoice(value)}>{icon}{text}</button>)}</div></div>
      <div className="settingsRow"><span><b><Languages size={15}/> {t('language_label')}</b></span>
        <div className="segmented" role="radiogroup" aria-label={t('language_label')}>{(['it', 'en'] as const).map((value) =>
          <button key={value} role="radio" aria-checked={getLang() === value} className={getLang() === value ? 'active' : ''} onClick={() => setLang(value)}>{value === 'it' ? 'Italiano' : 'English'}</button>)}</div></div>
    </section>
    {isDesktop && <>
      <section className="settingsCard" aria-labelledby="set-ai"><h2 id="set-ai"><Sparkles size={18}/>{t('desktop_ai_title')}</h2><DesktopAIInstaller/></section>
      <section className="settingsCard" aria-labelledby="set-up"><h2 id="set-up"><ShieldCheck size={18}/>{t('desktop_update_title')}</h2><DesktopUpdate/></section>
      <section className="settingsCard" aria-labelledby="set-perf"><h2 id="set-perf"><Cpu size={18}/>{t('settings_performance')}</h2>
        <div className="settingsRow"><span><b>{t('desktop_encoding')}</b><small>{t('settings_encoder_hint')}</small></span><strong>{vendor(health?.video?.selected)}</strong></div>
        {health?.video?.last_operation && <div className="settingsRow"><span><b>{t('desktop_last_encode')}</b></span><strong>{vendor(health.video.last_operation.encoder)}{health.video.last_operation.fallback ? ` · ${t('desktop_fallback')}` : ''}</strong></div>}
        <div className="settingsRow"><span><b><MonitorPlay size={15}/> {t('settings_playback')}</b><small>{t('desktop_playback_hint')}</small></span><strong>{t('settings_playback_browser')}</strong></div>
      </section>
      <section className="settingsCard" aria-labelledby="set-diag"><h2 id="set-diag"><Stethoscope size={18}/>{t('diagnostics_title')}</h2><DesktopDiagnostics/></section>
      <section className="settingsCard" aria-labelledby="set-data"><h2 id="set-data"><Database size={18}/>{t('settings_data')}</h2>
        <div className="settingsRow"><span><b>{t('settings_backups')}</b><small>{t('settings_backups_hint')}</small></span></div></section>
    </>}
  </main>;
}
