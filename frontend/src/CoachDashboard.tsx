import {useEffect,useMemo,useState} from 'react';
import {api} from './api';
import type {Team} from './types';
import {getLang,t,useI18n} from './i18n';
import {TrendingDown,TrendingUp,Minus,RotateCcw} from 'lucide-react';
import './dashboard.css';

type Trend={recent:number|null;previous:number|null;delta:number|null;delta_pct:number|null;slope:number|null;window:number};
type Metric={name:string;group:string;source:string;kind:'count'|'ratio';total:number;per_match:number;against_total:number;against_per_match:number;trend:Trend;event_ids:string[]};
type Row={id:string;date:string;season:string;competition:string;location:'home'|'away';opponent:string;goals_for:number|null;goals_against:number|null;result:'W'|'D'|'L'|null;events:number;events_against:number;unassigned_events:number;metrics:Record<string,number>;against:Record<string,number>};
type Data={team:{id:string;name:string};available:{seasons:string[];competitions:string[];opponents:{id:string;name:string}[];players:{id:string;name:string;shirt_number?:number;position?:string}[]};
 record:{played:number;with_score:number;W:number;D:number;L:number;goals_for:number;goals_against:number;points:number;form:string[]};matches:Row[];metrics:Metric[];
 categories:{name:string;for:number;against:number}[];minutes:{bucket:string;for:number;against:number}[];zones:{rows:number;columns:number;counts:number[][];located:number;total:number};
 players:{id:string;name:string;shirt_number?:number;position?:string;events:number;matches:number;metrics:Record<string,number>;top_categories:[string,number][]}[];unassigned_included:number;official?:Official[]};
type OfficialRow={id:string;date:string;round:string|null;location:'home'|'away';opponent:string;goals_for?:number;goals_against?:number;result?:'W'|'D'|'L'|null};
type Official={provider:string;competition:string;season:string;record:{played:number;W:number;D:number;L:number;goals_for:number;goals_against:number;points:number;form:string[]};results:OfficialRow[];upcoming:OfficialRow[]};
type Filters={team_id:string;season:string;competition:string;date_from:string;date_to:string;location:string;opponent_id:string;result:string;last:string;player_id:string;include_unassigned:boolean};

const EMPTY:Omit<Filters,'team_id'>={season:'',competition:'',date_from:'',date_to:'',location:'',opponent_id:'',result:'',last:'',player_id:'',include_unassigned:true};
const GROUPS=['overview','attacking','passing','defensive','transition','possession','goalkeeping'];
const KEY='touchline_dashboard';
const nf=(digits:number)=>new Intl.NumberFormat(getLang()==='it'?'it-IT':'en-GB',{maximumFractionDigits:digits,minimumFractionDigits:0});
const fmt=(v:number|null|undefined,ratio=false)=>v==null?'—':nf(ratio?1:Number.isInteger(v)?0:1).format(v);
const day=(iso:string,short=false)=>new Date(iso+'T12:00').toLocaleDateString(getLang()==='it'?'it-IT':'en-GB',short?{day:'2-digit',month:'2-digit'}:{day:'2-digit',month:'2-digit',year:'numeric'});
const label=(name:string)=>{const k='stat_'+name.replace(/[^a-z0-9]+/gi,'_').replace(/_+$/,'').toLowerCase();const v=t(k);return v===k?name:v};

function Sparkline({values,height=34,width=120}:{values:number[];height?:number;width?:number}){
 if(values.length<2)return <svg className="spark" width={width} height={height} aria-hidden="true"/>;
 const max=Math.max(...values),min=Math.min(...values),span=max-min||1;
 const pts=values.map((v,i)=>`${(i/(values.length-1))*(width-4)+2},${height-2-((v-min)/span)*(height-4)}`).join(' ');
 return <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true"><polyline points={pts} fill="none" strokeWidth="2"/></svg>
}

function TrendBadge({trend,ratio}:{trend:Trend;ratio:boolean}){
 if(trend.delta==null||!trend.window)return <span className="trend flat" title={t('dash_trend_need_more')}><Minus size={13}/>{t('dash_trend_na')}</span>;
 const up=trend.delta>0,down=trend.delta<0;
 const text=trend.delta_pct!=null&&!ratio?`${up?'+':''}${fmt(trend.delta_pct,true)}%`:`${up?'+':''}${fmt(trend.delta,true)}${ratio?' '+t('dash_points_short'):''}`;
 return <span className={`trend ${up?'up':down?'down':'flat'}`} title={t('dash_trend_tip',{n:String(trend.window),recent:fmt(trend.recent),previous:fmt(trend.previous)})}>{up?<TrendingUp size={13}/>:down?<TrendingDown size={13}/>:<Minus size={13}/>}{text}</span>
}

function TrendChart({rows,metric}:{rows:Row[];metric:string}){
 const w=1160,h=240,pad=34;
 const ours=rows.map(r=>r.metrics[metric]??0),theirs=rows.map(r=>r.against[metric]??0);
 const tagged=rows.map(r=>r.events+r.events_against>0);
 if(rows.length<2)return <p className="muted">{t('dash_trend_need_more')}</p>;
 const max=Math.max(1,...ours,...theirs)*1.15;const x=(i:number)=>pad+i*(w-2*pad)/(rows.length-1);const y=(v:number)=>h-pad-(v/max)*(h-2*pad);
 const line=(vals:number[])=>vals.map((v,i)=>tagged[i]?`${x(i)},${y(v)}`:null).filter(Boolean).join(' ');
 const counted=ours.filter((_,i)=>tagged[i]);
 const top=Math.max(1,...ours,...theirs);const avg=counted.reduce((a,b)=>a+b,0)/Math.max(1,counted.length);
 return <svg className="trendChart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={t('dash_trend_chart',{metric:label(metric)})}>
  {[0,.5,1].map(f=><g key={f}><line className="grid" x1={pad} x2={w-pad} y1={y(top*f)} y2={y(top*f)}/><text className="axis" x={4} y={y(top*f)+4}>{fmt(Math.round(top*f*10)/10)}</text></g>)}
  <line className="avg" x1={pad} x2={w-pad} y1={y(avg)} y2={y(avg)}><title>{t('dash_average')}: {fmt(Math.round(avg*100)/100)}</title></line>
  <polyline className="ours" points={line(ours)}/><polyline className="against" points={line(theirs)}/>
  {rows.map((r,i)=><g key={r.id}><circle className={`dot ${r.result||'none'}`} cx={x(i)} cy={y(ours[i])} r="4.5"><title>{`${r.date} · ${r.opponent} · ${fmt(ours[i])}`}</title></circle>
   {(rows.length<=16||i%Math.ceil(rows.length/16)===0)&&<text className="axis" x={x(i)} y={h-10} textAnchor="middle">{day(r.date,true)}</text>}</g>)}
 </svg>
}

export function CoachDashboard({teams,openMatch}:{teams:Team[];openMatch:(id:string)=>void}){
 useI18n();
 const saved=useMemo(()=>{try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch{return {}}},[]);
 const[filters,setFilters]=useState<Filters>({team_id:'',...EMPTY,...saved});
 const[data,setData]=useState<Data|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const[group,setGroup]=useState('overview'),[metric,setMetric]=useState('goals'),[sort,setSort]=useState<{key:string;dir:1|-1}>({key:'date',dir:-1});
 useEffect(()=>{localStorage.setItem(KEY,JSON.stringify(filters))},[filters]);
 useEffect(()=>{let live=true;setBusy(true);setError('');
  const q=new URLSearchParams();Object.entries(filters).forEach(([k,v])=>{if(k==='include_unassigned'){if(!v)q.set(k,'false')}else if(v)q.set(k,String(v))});
  api<Data>('/dashboard/team?'+q).then(d=>{if(!live)return;setData(d);if(!filters.team_id)setFilters(f=>({...f,team_id:d.team.id}))})
   .catch(e=>{if(live){setData(null);setError((e as Error).message)}}).finally(()=>live&&setBusy(false));return()=>{live=false}},[JSON.stringify(filters)]);
 const set=(patch:Partial<Filters>)=>setFilters(f=>({...f,...patch}));
 const active=Object.entries(EMPTY).filter(([k,v])=>(filters as any)[k]!==v).length;
 const metrics=data?.metrics||[];const byName=Object.fromEntries(metrics.map(m=>[m.name,m]));
 const rows=data?.matches||[];
 const sorted=[...rows].sort((a,b)=>{const va:any=sort.key==='date'?a.date:sort.key==='opponent'?a.opponent:sort.key==='events'?a.events:(a.metrics[sort.key]??0);const vb:any=sort.key==='date'?b.date:sort.key==='opponent'?b.opponent:sort.key==='events'?b.events:(b.metrics[sort.key]??0);return (va>vb?1:va<vb?-1:0)*sort.dir});
 const th=(key:string,text:string,num=false)=><th key={key} className={num?'num':''}><button className={sort.key===key?'sorted':''} onClick={()=>setSort(s=>({key,dir:s.key===key?(s.dir===1?-1:1):-1}))}>{text}{sort.key===key?(sort.dir===1?' ▲':' ▼'):''}</button></th>;
 const zoneMax=Math.max(1,...(data?.zones.counts.flat()||[1]));const minuteMax=Math.max(1,...(data?.minutes||[]).flatMap(m=>[m.for,m.against]));
 const catMax=Math.max(1,...(data?.categories||[]).slice(0,12).flatMap(c=>[c.for,c.against]));
 const tableMetrics=['goals','shots','shots on target','passes','pass completion %','recoveries','turnovers'];
 const r=data?.record;
 return <main className="library dashboard">
  <div className="libraryTop"><div><p className="eyebrow">{t('dash_eyebrow')}</p><h1>{t('dash_title')}</h1><p>{data?t('dash_subtitle',{team:data.team.name}):t('dash_subtitle_empty')}</p></div></div>
  <section className="dashFilters" aria-label={t('dash_filters')}>
   {teams.length>1&&<label>{t('team')}<select value={filters.team_id} onChange={e=>set({team_id:e.target.value,opponent_id:'',player_id:''})}>{teams.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>}
   <label>{t('season')}<select value={filters.season} onChange={e=>set({season:e.target.value})}><option value="">{t('dash_all')}</option>{data?.available.seasons.map(s=><option key={s}>{s}</option>)}</select></label>
   <label>{t('dash_competition')}<select value={filters.competition} onChange={e=>set({competition:e.target.value})}><option value="">{t('dash_all')}</option>{data?.available.competitions.map(s=><option key={s}>{s}</option>)}</select></label>
   <label>{t('dash_from')}<input type="date" lang={getLang()} value={filters.date_from} onChange={e=>set({date_from:e.target.value})}/></label>
   <label>{t('dash_to')}<input type="date" lang={getLang()} value={filters.date_to} onChange={e=>set({date_to:e.target.value})}/></label>
   <label>{t('dash_venue')}<select value={filters.location} onChange={e=>set({location:e.target.value})}><option value="">{t('dash_all')}</option><option value="home">{t('dash_home')}</option><option value="away">{t('dash_away')}</option></select></label>
   <label>{t('dash_opponent')}<select value={filters.opponent_id} onChange={e=>set({opponent_id:e.target.value})}><option value="">{t('dash_all')}</option>{data?.available.opponents.map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
   <label>{t('dash_result')}<select value={filters.result} onChange={e=>set({result:e.target.value})}><option value="">{t('dash_all')}</option><option value="W">{t('dash_win')}</option><option value="D">{t('dash_draw')}</option><option value="L">{t('dash_loss')}</option></select></label>
   <label>{t('dash_last')}<select value={filters.last} onChange={e=>set({last:e.target.value})}><option value="">{t('dash_all')}</option>{[3,5,10,20].map(n=><option key={n} value={n}>{t('dash_last_n',{n:String(n)})}</option>)}</select></label>
   <label>{t('dash_player')}<select value={filters.player_id} onChange={e=>set({player_id:e.target.value})}><option value="">{t('dash_whole_team')}</option>{data?.available.players.map(p=><option key={p.id} value={p.id}>{p.shirt_number!=null?`${p.shirt_number} · `:''}{p.name}</option>)}</select></label>
   <label className="check"><input type="checkbox" checked={filters.include_unassigned} onChange={e=>set({include_unassigned:e.target.checked})}/>{t('dash_include_unassigned')}</label>
   <button className="ghost" disabled={!active} onClick={()=>setFilters(f=>({...f,...EMPTY}))}><RotateCcw size={15}/>{t('dash_reset',{n:String(active)})}</button>
  </section>
  {error&&<div className="error" role="alert">{error}</div>}
  {busy&&!data&&<p className="muted" role="status">{t('loading')}</p>}
  {data?.official?.map(o=><section className="dashCard dashOfficial" key={o.provider+o.competition+o.season}>
   <div className="dashCardHead"><h2>{t('dash_official')}</h2><small className="muted">{o.competition} · {o.season}</small></div>
   <div className="dashOfficialSummary">
    <span><small>{t('dash_played')}</small><b>{o.record.played}</b></span>
    <span><small>{t('dash_record')}</small><b>{o.record.W}-{o.record.D}-{o.record.L}</b></span>
    <span><small>{t('dash_goals')}</small><b>{o.record.goals_for}:{o.record.goals_against}</b></span>
    <span><small>{t('dash_points',{n:String(o.record.points)})}</small><b className="form">{o.record.form.length?o.record.form.map((x,i)=><i key={i} className={x}>{t('dash_res_'+x)}</i>):'—'}</b></span>
   </div>
   {o.results.length>0&&<table className="dashTable"><thead><tr><th>{t('date')}</th><th>{t('dash_round')}</th><th>{t('dash_opponent')}</th><th>{t('dash_venue')}</th><th>{t('dash_result')}</th></tr></thead><tbody>{[...o.results].reverse().map(m=><tr key={m.id}><td>{m.date}</td><td>{/^\d+/.exec(m.round||'')?.[0]||'—'}</td><td>{m.opponent}</td><td>{m.location==='home'?t('dash_home'):t('dash_away')}</td><td><span className={`res ${m.result}`}>{m.goals_for}:{m.goals_against}</span></td></tr>)}</tbody></table>}
   {o.upcoming.length>0&&<p className="dashNext"><b>{t('dash_next')}:</b> {o.upcoming.slice(0,3).map(m=>`${m.date} · ${m.location==='home'?t('dash_home'):t('dash_away')} · ${m.opponent}`).join('  —  ')}</p>}
   <p className="muted dashOfficialNote">{t('dash_official_note')}</p>
  </section>)}
  {data&&!rows.length&&<div className="empty"><h2>{data.official?.length?t('dash_no_analyzed'):t('dash_no_matches')}</h2><p>{t('dash_no_matches_hint')}</p></div>}
  {data&&rows.length>0&&r&&<>
   {data.unassigned_included>0&&<p className="notice">{t('dash_unassigned_note',{n:String(data.unassigned_included)})}</p>}
   <section className="dashKpis" aria-busy={busy}>
    <div className="kpi"><span>{t('dash_played')}</span><b>{r.played}</b><small>{r.with_score<r.played?t('dash_with_score',{n:String(r.with_score)}):'\u00a0'}</small></div>
    <div className="kpi"><span>{t('dash_record')}</span><b>{r.W}-{r.D}-{r.L}</b><small>{t('dash_points',{n:String(r.points)})}{r.with_score?` · ${nf(2).format(r.points/r.with_score)}/${t('dash_ppg_short')}`:''}</small></div>
    <div className="kpi"><span>{t('dash_goals')}</span><b>{r.goals_for}:{r.goals_against}</b><small>{t('dash_goal_diff')} {r.goals_for-r.goals_against>0?'+':''}{r.goals_for-r.goals_against}</small></div>
    <div className="kpi"><span>{t('dash_form')}</span><b className="form">{r.form.length?r.form.map((x,i)=><i key={i} className={x}>{t('dash_res_'+x)}</i>):'—'}</b><small>{t('dash_form_hint')}</small></div>
    {['shots','pass completion %','recoveries'].map(n=>byName[n]&&<div className="kpi" key={n}><span>{label(n)}</span><b>{fmt(byName[n].per_match,byName[n].kind==='ratio')}{byName[n].kind==='ratio'&&n.includes('%')?'%':''}</b><small><TrendBadge trend={byName[n].trend} ratio={byName[n].kind==='ratio'}/> {byName[n].kind==='count'?t('dash_per_match'):''}</small></div>)}
   </section>

   <section className="dashCard">
    <div className="dashCardHead"><h2>{t('dash_trend')}</h2><label>{t('dash_metric')}<select value={metric} onChange={e=>setMetric(e.target.value)}>{GROUPS.map(g=><optgroup key={g} label={t('dash_group_'+g)}>{metrics.filter(m=>m.group===g).map(m=><option key={m.name} value={m.name}>{label(m.name)}</option>)}</optgroup>)}</select></label></div>
    <TrendChart rows={rows} metric={metric}/>
    <p className="legend"><i className="ours"/>{data.team.name} <i className="against"/>{t('dash_opponents')} <i className="avg"/>{t('dash_average')} <span className="dot W"/>{t('dash_win')} <span className="dot D"/>{t('dash_draw')} <span className="dot L"/>{t('dash_loss')} <span className="dot none"/>{t('dash_no_score')}</p>
   </section>

   <section className="dashCard">
    <div className="dashCardHead"><h2>{t('dash_metrics')}</h2><div className="statTabs">{GROUPS.filter(g=>metrics.some(m=>m.group===g)).map(g=><button key={g} className={group===g?'active':''} onClick={()=>setGroup(g)}>{t('dash_group_'+g)}</button>)}</div></div>
    <table className="dashTable metricTable"><thead><tr><th>{t('dash_metric')}</th><th className="num">{t('dash_total')}</th><th className="num">{t('dash_per_match')}</th><th className="num">{t('dash_opponents')}</th><th>{t('dash_trend')}</th><th>{t('dash_by_match')}</th></tr></thead>
     <tbody>{metrics.filter(m=>m.group===group).map(m=>{const ratio=m.kind==='ratio';return <tr key={m.name} className={metric===m.name?'selected':''} onClick={()=>setMetric(m.name)}>
      <td><b>{label(m.name)}</b><small>{t(m.source==='calculated'?'dash_calculated':'dash_tagged')}</small></td>
      <td className="num">{fmt(m.total,ratio)}</td><td className="num">{ratio?'—':fmt(m.per_match)}</td><td className="num">{ratio?fmt(m.against_total,true):fmt(m.against_per_match)}</td>
      <td><TrendBadge trend={m.trend} ratio={ratio}/></td><td><Sparkline values={rows.map(x=>x.metrics[m.name]??0)}/></td></tr>})}</tbody></table>
   </section>

   <div className="dashGrid">
    <section className="dashCard"><h2>{t('dash_minutes')}</h2>
     <div className="bars">{data.minutes.map(m=><div key={m.bucket} className="barGroup"><div className="barPair"><span className="bar ours" style={{height:`${m.for/minuteMax*100}%`}} title={`${m.for}`}><em>{m.for||''}</em></span><span className="bar against" style={{height:`${m.against/minuteMax*100}%`}} title={`${m.against}`}><em>{m.against||''}</em></span></div><small>{m.bucket}'</small></div>)}</div>
     <p className="muted">{t('dash_minutes_hint')}</p></section>
    <section className="dashCard"><h2>{t('dash_zones')}</h2>
     {data.zones.located?<div className="zoneGrid" style={{gridTemplateColumns:`repeat(${data.zones.columns},1fr)`}}>{data.zones.counts.flatMap((row,ri)=>row.map((v,ci)=><span key={`${ri}-${ci}`} className={v/zoneMax>.55?'hot':''} style={{['--heat' as any]:v/zoneMax}} title={`${v}`}>{v||''}</span>))}</div>:<p className="muted">{t('dash_zones_empty')}</p>}
     <p className="muted">{t('dash_zones_attack')} · {t('dash_zones_hint',{n:String(data.zones.located),total:String(data.zones.total)})}</p></section>
   </div>

   <section className="dashCard"><h2>{t('dash_categories')}</h2>
    <div className="dashCatBars">{data.categories.slice(0,12).map(c=><div key={c.name} className="dashCatRow"><span>{c.name}</span><div><i className="ours" style={{width:`${c.for/catMax*100}%`}}/><i className="against" style={{width:`${c.against/catMax*100}%`}}/></div><b>{c.for}<small> / {c.against}</small></b></div>)}</div></section>

   {!filters.player_id&&data.players.length>0&&<section className="dashCard"><h2>{t('dash_players')}</h2>
    <table className="dashTable"><thead><tr><th>{t('dash_player')}</th><th className="num">{t('dash_matches')}</th><th className="num">{t('dash_events')}</th><th className="num">{label('goals')}</th><th className="num">{label('shots')}</th><th className="num">{label('passes')}</th><th>{t('dash_top_actions')}</th><th/></tr></thead>
     <tbody>{data.players.map(p=><tr key={p.id}><td><b>{p.shirt_number!=null?`${p.shirt_number} · `:''}{p.name}</b><small>{p.position||''}</small></td><td className="num">{p.matches}</td><td className="num">{p.events}</td><td className="num">{p.metrics['goals']??0}</td><td className="num">{p.metrics['shots']??0}</td><td className="num">{p.metrics['passes']??0}</td>
      <td>{p.top_categories.map(([n,c])=>`${n} ${c}`).join(' · ')}</td><td><button className="ghost small" onClick={()=>set({player_id:p.id})}>{t('dash_focus')}</button></td></tr>)}</tbody></table></section>}

   <section className="dashCard"><h2>{t('dash_matches')}</h2>
    <table className="dashTable"><thead><tr>{th('date',t('date'))}{th('opponent',t('dash_opponent'))}<th>{t('dash_venue')}</th><th>{t('dash_result')}</th>{th('events',t('dash_events'),true)}{tableMetrics.map(n=>th(n,label(n),true))}</tr></thead>
     <tbody>{sorted.map(x=><tr key={x.id} className="clickable" onClick={()=>openMatch(x.id)} title={t('dash_open_match')}>
      <td className="num">{day(x.date)}</td><td><b>{x.opponent}</b><small>{x.competition}</small></td><td>{t(x.location==='home'?'dash_home':'dash_away')}</td>
      <td>{x.result?<span className={`res ${x.result}`}>{x.goals_for}-{x.goals_against}</span>:<span className="res none" title={t('dash_no_score')}>—</span>}</td>
      <td className="num">{x.events}{x.events===0&&<small className="warn">{t('dash_not_tagged')}</small>}</td>{tableMetrics.map(n=><td className="num" key={n}>{fmt(x.metrics[n],n.includes('%'))}</td>)}</tr>)}</tbody></table></section>
  </>}
 </main>
}
