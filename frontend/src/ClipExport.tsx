import {useEffect,useState} from 'react';
import {post,api,formatTime} from './api';
import type {Event} from './types';
import {t} from './i18n';

export function ClipExport({event,hasUnsavedDrawings=false}:{event:Event;hasUnsavedDrawings?:boolean}){
 const[on,setOn]=useState(true),[freeze,setFreeze]=useState(true),[seconds,setSeconds]=useState(3),[header,setHeader]=useState(event.category.name),[minute,setMinute]=useState(formatTime(event.timestamp)),[note,setNote]=useState(event.note||''),[busy,setBusy]=useState(false),[job,setJob]=useState<any>(null),[progress,setProgress]=useState(0),[error,setError]=useState('');
 const team=event.team||'',player=event.players?.[0]?.player?.name||event.player?.name||'';
 const from=event.start??Math.max(0,event.timestamp-(event.category?.pre_roll??5)),to=event.end??(event.timestamp+(event.category?.post_roll??5));
 useEffect(()=>{setHeader(event.category.name);setMinute(formatTime(event.timestamp));setNote(event.note||'');setJob(null);setError('')},[event.id]);
 useEffect(()=>{setNote(event.note||'')},[event.note]);
 useEffect(()=>{if(!job||['completed','failed'].includes(job.status))return;const timer=window.setInterval(async()=>{try{const next=await api(`/jobs/${job.id}`);setProgress(next.progress||0);setJob(next)}catch(e){setError((e as Error).message);window.clearInterval(timer)}},750);return()=>window.clearInterval(timer)},[job?.id,job?.status]);
 const exportIt=async()=>{setBusy(true);setProgress(0);setJob(null);setError('');try{setJob(await post('/exports/clip',{video_id:event.video_id,event_id:event.id,start:from,end:to,include_annotations:on,freeze_seconds:freeze?seconds:0,overlay:on?{header,minute,team,player,note,pitch_x:event.pitch_x??null,pitch_y:event.pitch_y??null}:null}))}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 return <div className="clipExport"><label className="check aiChoice"><input type="checkbox" checked={on} onChange={e=>setOn(e.target.checked)}/><span><b>{t('export_saved_overlays')}</b></span></label>
  {on&&<div className="overlayFields"><div className="two"><label>{t('header')}<input value={header} onChange={e=>setHeader(e.target.value)}/></label><label>{t('minute')}<input value={minute} onChange={e=>setMinute(e.target.value)}/></label></div><label>{t('note')}<input value={note} onChange={e=>setNote(e.target.value)}/></label></div>}
  <div className="freezeControls"><label className="check"><input type="checkbox" checked={freeze} onChange={e=>setFreeze(e.target.checked)}/>{t('export_freeze')}</label>{freeze&&<label>{t('freeze_seconds')}<input type="number" min="1" max="10" step="1" value={seconds} onChange={e=>setSeconds(Math.max(1,Math.min(10,Number(e.target.value)||1)))}/></label>}</div>
  {on&&hasUnsavedDrawings&&<p className="error" role="status">{t('drawing_unsaved')}</p>}
  <p className="overlayPreview muted" role="status">{t('clip_window',{from:formatTime(from),to:formatTime(to)})}</p>
  <button className="primary wide" disabled={busy||(on&&hasUnsavedDrawings)||!!job&&['queued','running'].includes(job.status)} onClick={()=>void exportIt()}>{t('export_clip')}</button>
  {error&&<div className="error" role="alert">{error}</div>}{job&&<div className="jobStatus" role="status"><div>{t(job.status==='completed'?'clip_ready':job.status==='failed'?'clip_failed':'clip_processing')} {job.status!=='completed'&&job.status!=='failed'&&`${progress}%`}</div><progress value={progress} max="100"/>{job.status==='completed'&&<a className="primary" href={`/api/jobs/${job.id}/download`} download>{t('download_clip')}</a>}{job.status==='failed'&&<span className="error">{job.error}</span>}</div>}
 </div>
}
