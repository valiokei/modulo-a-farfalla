import {useEffect, useState} from 'react';
import {AlertTriangle, Cpu, MonitorPlay} from 'lucide-react';
import {t, useI18n} from './i18n';
import './desktop.css';
import {DesktopUpdate} from './DesktopUpdate';

export const isDesktop = import.meta.env.VITE_DESKTOP === 'true';

type VideoStatus = {
  selected: string;
  last_operation?: {encoder: string; decoder: string; fallback: boolean};
};

export function DesktopAIWarning() {
  return <p className="desktopAiWarning" role="status"><AlertTriangle size={18}/>{t('desktop_ai_unavailable')}</p>;
}

export function DesktopStatus() {
  useI18n();
  const [video, setVideo] = useState<VideoStatus>();
  const [failed, setFailed] = useState(false);
  const [playback, setPlayback] = useState('desktop_playback_unknown');
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
        if (!stopped) {setVideo(health.video); setFailed(false);}
      } catch {if (!stopped) setFailed(true);}
    };
    void poll();
    const timer = setInterval(poll, 5000);
    const checkPlayback = async (event: Event) => {
      const element = event.target;
      if (!(element instanceof HTMLVideoElement) || !navigator.mediaCapabilities) return;
      try {
        const result = await navigator.mediaCapabilities.decodingInfo({
          type: 'file',
          video: {contentType: 'video/mp4; codecs="avc1.640033"',
            width: element.videoWidth, height: element.videoHeight,
            bitrate: 8_000_000, framerate: 30}
        });
        if (!stopped) setPlayback(result.supported
          ? (result.powerEfficient ? 'desktop_playback_efficient' : 'desktop_playback_software')
          : 'desktop_playback_unknown');
      } catch {if (!stopped) setPlayback('desktop_playback_unknown');}
    };
    document.addEventListener('loadedmetadata', checkPlayback, true);
    return () => {stopped = true; clearInterval(timer); document.removeEventListener('loadedmetadata', checkPlayback, true);};
  }, []);
  if (!isDesktop) return null;
  const vendor = (value?: string) => value === 'cpu' ? 'CPU' : value?.toUpperCase();
  return <aside className="desktopStatus" aria-label={t('desktop_video_status')}>
    <span><Cpu size={18}/><b>{t('desktop_encoding')}:</b> {failed ? t('desktop_unavailable') :
      video ? vendor(video.selected) : t('desktop_detecting')}</span>
    {video?.last_operation && <span><b>{t('desktop_last_encode')}:</b> {vendor(video.last_operation.encoder)}
      {video.last_operation.fallback && <em>{t('desktop_fallback')}</em>}</span>}
    <span title={t('desktop_playback_hint')}><MonitorPlay size={18}/>{t(playback)}</span>
    <DesktopAIWarning/>
    <DesktopUpdate/>
  </aside>;
}
