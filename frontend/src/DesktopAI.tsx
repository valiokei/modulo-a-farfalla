import {useEffect,useState} from 'react';
import {Download, RefreshCw, Settings, Sparkles, Trash2} from 'lucide-react';
import {t,useI18n} from './i18n';
import {AIReview} from './AIReview';
import type {Category,Video} from './types';

const isDesktop = import.meta.env.VITE_DESKTOP === 'true';
const busyPhases = ['starting','downloading','verifying','extracting'];
const errorCodes = ['disk','asset','metadata','extract','unsupported','unexpected','http','network','dns','tls','proxy','timeout'];

export type AiState = {phase?:string; supported?:boolean; active?:boolean; progress?:number;
  downloaded_bytes?:number; total_bytes?:number; error?:string; version?:string; size_bytes?:number};

const size = (bytes?: number) => bytes && bytes > 0 ? `${(bytes / 1073741824).toFixed(2)} GB` : '';

export function useAiState(){
  const [state,setState]=useState<AiState>();
  const busyPhase=busyPhases.includes(state?.phase||'');
  useEffect(()=>{
    if(!isDesktop)return;
    let stopped=false;
    const poll=async()=>{
      try{const response=await fetch('/desktop/ai/status',{cache:'no-store'});const body=await response.json();if(!stopped)setState(body)}
      catch{/* the next tick retries */}
    };
    void poll();
    const timer=window.setInterval(()=>void poll(),busyPhase?1500:30000);
    return()=>{stopped=true;window.clearInterval(timer)};
  },[busyPhase]);
  return [state,setState,busyPhase] as const;
}

/** Install / repair / remove the on-demand runtime. Lives in Settings → AI. */
export function DesktopAIInstaller(){
  useI18n();
  const [state,setState,busyPhase]=useAiState();
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  if(!isDesktop)return null;
  const act=async(path:string,confirmKey:string)=>{
    if(!window.confirm(t(confirmKey)))return;
    setBusy(true);setMessage('');
    try{
      const response=await fetch(path,{method:'POST'});
      const body=await response.json();
      if(!response.ok)throw new Error(body.detail||t('desktop_ai_error'));
      setState(body);
    }catch(error){setMessage((error as Error).message||t('desktop_ai_error'))}
    finally{setBusy(false)}
  };
  const error=state?.error?(errorCodes.includes(state.error)?t(`desktop_ai_error_${state.error}`):t('desktop_ai_error')):'';
  const label=state?.phase==='partial'?t('desktop_ai_partial'):state?.phase==='failed'?t('desktop_ai_failed'):t('desktop_ai_not_installed');
  return <div className="desktopAi"><p>{t('desktop_ai_intro')}</p>
    {!state&&<p>{t('desktop_ai_checking')}</p>}
    {state&&<div className={`desktopAiCard ${state.phase||''}`}>
      {busyPhase?<>
        <b>{state.phase==='extracting'||state.phase==='verifying'?t('desktop_ai_extracting'):t('desktop_ai_downloading')}</b>
        <progress value={state.progress||0}max="100"/>
        <small>{t('desktop_ai_progress',{n:String(state.progress||0)})}{state.phase==='downloading'&&state.total_bytes?` · ${size(state.downloaded_bytes)} / ${size(state.total_bytes)}`:''}</small>
      </>:state.active?<>
        <b>{t('desktop_ai_active')}</b>
        {state.version&&<small>{t('desktop_ai_version',{v:state.version})}{state.size_bytes?` · ${size(state.size_bytes)}`:''}</small>}
        <button type="button"disabled={busy}onClick={()=>void act('/desktop/ai/remove','desktop_ai_remove_confirm')}><Trash2 size={15}/>{t('desktop_ai_remove')}</button>
      </>:state.phase==='ready'?<>
        <b>{t('desktop_ai_ready')}</b><small>{t('desktop_ai_restart_hint')}</small>
        {state.version&&<small>{t('desktop_ai_version',{v:state.version})}{state.size_bytes?` · ${size(state.size_bytes)}`:''}</small>}
        <button type="button"disabled={busy}onClick={()=>void act('/desktop/ai/remove','desktop_ai_remove_confirm')}><Trash2 size={15}/>{t('desktop_ai_remove')}</button>
      </>:state.supported?<>
        <b>{label}</b><small>{t('desktop_ai_install_hint')}</small>
        <button className="primary"type="button"disabled={busy}onClick={()=>void act('/desktop/ai/install','desktop_ai_confirm')}>{state.phase==='failed'||state.phase==='partial'?<RefreshCw size={16}/>:<Download size={16}/>}{state.phase==='failed'||state.phase==='partial'?t('desktop_ai_retry'):t('desktop_ai_install')}</button>
      </>:<b>{t('desktop_ai_unsupported')}</b>}
      {error&&<p className="error"role="alert">{error}</p>}
      {message&&<p className="error"role="alert">{message}</p>}
    </div>}
  </div>;
}

/** Match AI tab: review when the runtime is active, otherwise a pointer to Settings. */
export function DesktopAI({video,categories,reload,seek,openSettings}:{video:Video;categories:Category[];reload:()=>void;seek:(n:number)=>void;openSettings?:()=>void}) {
  useI18n();
  const [state]=useAiState();
  if(!isDesktop||state?.active)return <AIReview video={video}categories={categories}reload={reload}seek={seek}/>;
  return <div className="aiPanel desktopAi"><h2><Sparkles size={19}/>{t('desktop_ai_title')}</h2>
    {!state?<p>{t('desktop_ai_checking')}</p>:<div className={`desktopAiCard ${state.phase||''}`}>
      <b>{state.phase==='ready'?t('desktop_ai_ready'):busyPhases.includes(state.phase||'')?t('desktop_ai_downloading'):state.supported?t('desktop_ai_not_installed'):t('desktop_ai_unsupported')}</b>
      <small>{state.phase==='ready'?t('desktop_ai_restart_hint'):t('desktop_ai_settings_hint')}</small>
      {openSettings&&state.supported&&state.phase!=='ready'&&<button className="primary"type="button"onClick={openSettings}><Settings size={16}/>{t('desktop_ai_open_settings')}</button>}
    </div>}
  </div>;
}
