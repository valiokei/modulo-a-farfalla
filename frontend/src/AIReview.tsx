import {useEffect,useRef,useState} from 'react';
import {api,formatTime,post} from './api';
import type {Category,Team,Video} from './types';
import {t} from './i18n';

export function AIReview({video,categories,reload}:{video:Video;categories:Category[];reload:()=>void;seek?:(n:number)=>void}) {
 const [job,setJob]=useState<any>(),[selected,setSelected]=useState<any>(),[error,setError]=useState('');
 const [threshold,setThreshold]=useState(0),[filter,setFilter]=useState(''),[category,setCategory]=useState('');
 const [teams,setTeams]=useState<Team[]>([]),[team,setTeam]=useState(''),[actor,setActor]=useState(''),[receiver,setReceiver]=useState('');
 const [context,setContext]=useState(8),[busy,setBusy]=useState(false),[evidence,setEvidence]=useState(false);
 const player=useRef<HTMLVideoElement>(null);
 useEffect(()=>{api<Team[]>('/teams').then(setTeams).catch(e=>setError(e.message))},[]);
 useEffect(()=>{
   let stopped=false;let timer:ReturnType<typeof setTimeout>;
   setJob(undefined);setSelected(undefined);
   const poll=async()=>{
     try {const next:any=await api(`/videos/${video.id}/ai-job`);if(stopped)return;setJob(next);setSelected((old:any)=>next.suggestions?.find((s:any)=>s.id===old?.id));if(['queued','running'].includes(next.status))timer=setTimeout(poll,2000)}
     catch(e){if(!stopped&&video.ai_job_id)setError((e as Error).message)}
   };
   if(video.status==='ready')void poll();
   return()=>{stopped=true;clearTimeout(timer)};
 },[video.id,video.status,video.ai_job_id,video.ai_status]);
 const suggestions=(job?.suggestions||[]).filter((s:any)=>s.confidence>=threshold&&(!filter||s.proposed_category===filter));
 const players=teams.find(t=>t.id===team)?.players||[];
 const choose=(s:any)=>{setSelected(s);setCategory(s.corrected_data?.category_id||categories.find(c=>c.name===s.proposed_category)?.id||'');setTeam(s.corrected_data?.team_id||s.proposed_team_id||'');const mapped=s.corrected_data?.players||s.proposed_players||[];setActor(mapped.find((p:any)=>p.role==='actor')?.player_id||'');setReceiver(mapped.find((p:any)=>p.role==='receiver')?.player_id||'')};
 useEffect(()=>{if(player.current&&selected){player.current.currentTime=Math.max(0,selected.timestamp-context);void player.current.play().catch(()=>{})}},[selected?.id,context]);
 const refresh=async()=>{const next:any=await api(`/ai/jobs/${job.id}`);setJob(next);setSelected((old:any)=>next.suggestions.find((s:any)=>s.id===old?.id));reload()};
 const decide=async(action:'accept'|'edit'|'reject')=>{
   if(!selected||busy)return;setBusy(true);setError('');
   try{await post(`/ai/suggestions/${selected.id}`,{action,...(action==='reject'?{}:{category_id:category,team_id:team||null,players:[...(actor?[{player_id:actor,role:'actor'}]:[]),...(receiver?[{player_id:receiver,role:'receiver'}]:[])]})});await refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}
 };
 const move=(offset:number)=>{const index=suggestions.findIndex((s:any)=>s.id===selected?.id);if(suggestions[index+offset])choose(suggestions[index+offset])};
 useEffect(()=>{const key=(e:KeyboardEvent)=>{if((e.target as HTMLElement).matches('input,select,textarea'))return;if(selected?.status==='pending'&&e.key.toLowerCase()==='a')void decide('accept');if(selected?.status==='pending'&&e.key.toLowerCase()==='r')void decide('reject');if(e.key==='[')move(-1);if(e.key===']')move(1)};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)},[selected,category,team,actor,receiver,busy,suggestions]);
 return <div className="aiPanel"><h2>{t('review_title')}</h2><p>{t('ai_intro')}</p>{error&&<div role="alert"className="error">{error}</div>}
 {(!job||job.status==='failed'||job.status==='completed')&&<button className="primary"disabled={busy||video.status!=='ready'}onClick={async()=>{setBusy(true);try{const next=await post('/ai/jobs',{video_id:video.id,config:{mode:'fast'}});setJob(next);reload()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>{job?t('run_new'):t('fast')}</button>}
 {job&&<><p>{job.config?.stage||job.status} · {job.progress}%</p>{['queued','running'].includes(job.status)&&<progress value={job.progress}max="100"/>}{job.error&&<div className="error">{job.error}</div>}
 <div className="aiFilters"><label>{t('min_confidence',{n:String(Math.round(threshold*100))})}<input type="range"min="0"max="1"step=".01"value={threshold}onChange={e=>setThreshold(+e.target.value)}/></label><label>{t('filter_action')}<select value={filter}onChange={e=>setFilter(e.target.value)}><option value="">{t('all_actions')}</option>{categories.map(c=><option key={c.id}>{c.name}</option>)}</select></label></div>
 {job.status==='completed'&&suggestions.length===0&&<p>{t('no_candidates')}</p>}
 <div className="suggestionList">{suggestions.map((s:any)=><button className={`suggestion ${selected?.id===s.id?'selected':''}`}key={s.id}onClick={()=>choose(s)}><span>{formatTime(s.timestamp)}</span><b>{s.proposed_category}</b><em>{(s.confidence*100).toFixed(1)}%</em><small>{s.status}</small></button>)}</div>
 {selected&&<div className="aiReview"><div className="reviewNav"><button onClick={()=>move(-1)}>{t('previous_bracket')}</button><button onClick={()=>move(1)}>{t('next_bracket')}</button></div><h3>{selected.proposed_category} · {formatTime(selected.timestamp)}</h3>
 <video key={selected.id}ref={player}controls src={`/api/videos/${video.id}/stream`}onLoadedMetadata={e=>{e.currentTarget.currentTime=Math.max(0,selected.timestamp-context)}}onTimeUpdate={e=>{if(e.currentTarget.currentTime>=selected.timestamp+context)e.currentTarget.pause()}}/>
 <label>{t('context_before')}<input type="number"min="1"max="60"value={context}onChange={e=>setContext(Math.max(1,Math.min(60,+e.target.value)))}/></label>
 <p>{t('action_confidence',{n:String((selected.confidence*100).toFixed(1))})}{selected.confidence<.5?t('low_confidence'):''}</p>
 <label>{t('action')}<select value={category}onChange={e=>setCategory(e.target.value)}>{categories.map(c=><option key={c.id}value={c.id}>{c.name}</option>)}</select></label>
 <label>{t('team')}<select value={team}onChange={e=>{setTeam(e.target.value);setActor('');setReceiver('')}}><option value="">{t('unknown')}</option>{teams.map(t=><option value={t.id}key={t.id}>{t.name}</option>)}</select></label>
 <label>{t('actor_role')}<select value={actor}onChange={e=>setActor(e.target.value)}><option value="">{t('unknown')}</option>{players.map(p=><option key={p.id}value={p.id}>#{p.shirt_number??'–'} {p.name}</option>)}</select></label>
 <label>{t('receiver_secondary')}<select value={receiver}onChange={e=>setReceiver(e.target.value)}><option value="">{t('unknown')}</option>{players.map(p=><option key={p.id}value={p.id}>#{p.shirt_number??'–'} {p.name}</option>)}</select></label>
 <p>Pitch position: {selected.pitch_position?.join(', ')||'Unknown — tracking evidence unavailable'}</p><p>Source: {selected.evidence?.source||selected.evidence?.method||'Unknown'}<br/>Model: {selected.evidence?.model||'Legacy candidate'}</p>
 <label className="check"><input type="checkbox"checked={evidence}onChange={e=>setEvidence(e.target.checked)}/> {t('show_provenance')}</label>{evidence&&<pre>{JSON.stringify(selected.evidence,null,2)}</pre>}
 {selected.status==='pending'&&<div className="actions"><button disabled={busy}onClick={()=>decide('edit')}>{t('save_edits')}</button><button disabled={busy}onClick={()=>decide('reject')}>{t('reject')}</button><button disabled={busy||!category}className="primary"onClick={()=>decide('accept')}>{t('accept')}</button></div>}</div>}</>}
 </div>
}
