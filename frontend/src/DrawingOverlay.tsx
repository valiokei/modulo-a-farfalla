import {useEffect,useRef,useState} from 'react';
import type {PointerEvent} from 'react';
import {Check,MoveUpRight,Pencil,Pentagon,Redo2,Save,Trash2,Undo2,X} from 'lucide-react';
import {api,post,formatTime} from './api';
import type {Event,Shape} from './types';
import {t} from './i18n';
import './review.css';

type Annotation={id:string;timestamp:number;shapes:Shape[]};
export function DrawingOverlay({event,current,aspect=16/9,onDirty,open,setOpen,captureFrame,showFrame}:{event:Event;current:number;aspect?:number;onDirty?:(value:boolean)=>void;open:boolean;setOpen:(value:boolean)=>void;captureFrame:()=>number;showFrame:(time:number)=>void}){
 const [tool,setTool]=useState('pen'),[shapes,setShapes]=useState<Shape[]>([]),[redo,setRedo]=useState<Shape[]>([]),[draft,setDraft]=useState<Shape>(),[color,setColor]=useState('#ffdf36'),[width,setWidth]=useState(5),[dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[frame,setFrame]=useState(event.timestamp);
 const [loading,setLoading]=useState(true);
 const root=useRef<HTMLDivElement>(null),stroke=useRef<Shape|undefined>(undefined),pointer=useRef<number|undefined>(undefined),annotationId=useRef<string|undefined>(undefined);
 useEffect(()=>{onDirty?.(dirty)},[dirty,onDirty]);
 useEffect(()=>{let active=true;setLoading(true);annotationId.current=undefined;stroke.current=undefined;pointer.current=undefined;setDraft(undefined);setShapes([]);setRedo([]);setDirty(false);setError('');api<Annotation[]>(`/events/${event.id}/annotations`).then(rows=>{if(active){annotationId.current=rows[0]?.id;setShapes(rows[0]?.shapes||[]);setFrame(rows[0]?.timestamp??event.timestamp)}}).catch(e=>{if(active)setError((e as Error).message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[event.id]);
 useEffect(()=>{if(!open||loading||error)return;if(annotationId.current||dirty){showFrame(frame)}else{const captured=captureFrame();setFrame(captured);showFrame(captured)}},[open,loading]);
 const point=(e:PointerEvent<HTMLDivElement>):[number,number]=>{const r=root.current!.getBoundingClientRect();return[Math.min(1,Math.max(0,(e.clientX-r.left)/r.width)),Math.min(1,Math.max(0,(e.clientY-r.top)/r.height))]};
 const down=(e:PointerEvent<HTMLDivElement>)=>{if(!open||busy||loading||error||!e.isPrimary||e.button!==0||(e.target as HTMLElement).closest?.('.drawTools,.drawToggle'))return;e.preventDefault();e.stopPropagation();showFrame(frame);const[x,y]=point(e);const shape:Shape={type:tool,x1:x,y1:y,x2:x,y2:y,color,lineWidth:width,fill:tool==='polygon'?color+'55':'none',opacity:.95,visible:true,start:event.start,end:event.end,...(['pen','polygon'].includes(tool)?{points:[[x,y] as [number,number]]}:{})};stroke.current=shape;pointer.current=e.pointerId;setDraft(shape);e.currentTarget.setPointerCapture(e.pointerId)};
 const move=(e:PointerEvent<HTMLDivElement>)=>{if(pointer.current!==e.pointerId||!stroke.current)return;e.preventDefault();const[x,y]=point(e),old=stroke.current;const next={...old,x2:x,y2:y,points:old.points&&old.points.length<4096?[...old.points,[x,y] as [number,number]]:old.points};stroke.current=next;setDraft(next)};
 const finish=(e:PointerEvent<HTMLDivElement>)=>{if(pointer.current!==e.pointerId)return;e.preventDefault();move(e);const completed=stroke.current;stroke.current=undefined;pointer.current=undefined;setDraft(undefined);if(completed){setShapes(s=>[...s,completed]);setRedo([]);setDirty(true)}if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId)};
 const cancel=(e:PointerEvent<HTMLDivElement>)=>{if(pointer.current===e.pointerId){stroke.current=undefined;pointer.current=undefined;setDraft(undefined)}};
 const save=async()=>{setBusy(true);setError('');try{const payload={timestamp:frame,start:event.start,end:event.end,coordinate_mode:'screen',shapes};const row=annotationId.current?await api<Annotation>(`/annotations/${annotationId.current}`,{method:'PUT',body:JSON.stringify(payload)}):await post(`/events/${event.id}/annotations`,payload);annotationId.current=row.id;setDirty(false);setRedo([])}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const tools=[['pen',Pencil],['polygon',Pentagon],['arrow',MoveUpRight]] as const;
 const colors=[['yellow','#ffdf36'],['orange','#ff8c42'],['blue','#42d6ff'],['green','#7ee07e'],['pink','#ff5b9a']];
 return <div ref={root} className={`drawing ${open?'open':''}`} onPointerDown={down} onPointerMove={move} onPointerUp={finish} onPointerCancel={cancel} onLostPointerCapture={cancel}>
  <button className="drawToggle" type="button" disabled={!open&&(loading||!!error)} onClick={()=>setOpen(!open)} title={t(open?'drawing_close':'drawing_open')} aria-label={t(open?'drawing_close':'drawing_open')} aria-pressed={open}>{open?<X size={20}/>:<Pencil size={20}/>}</button>
  <svg viewBox={`0 0 1000 ${1000/aspect}`} preserveAspectRatio="none" aria-label={t('drawing_canvas')}>{[...shapes,...(draft?[draft]:[])].filter(s=>open||((s.start??event.start)<=current&&(s.end??event.end)>current)).map((s,i)=><ShapeView key={i} shape={s} height={1000/aspect}/>)}</svg>
  {open&&<div className="drawTools compact" onPointerDown={e=>e.stopPropagation()}>
   <div className="toolBtns">{tools.map(([key,Icon])=><button key={key} type="button" title={t(`drawing_${key}`)} aria-label={t(`drawing_${key}`)} aria-pressed={tool===key} className={tool===key?'active':''} onClick={()=>setTool(key)}><Icon size={19}/></button>)}</div>
   <div className="colorBtns">{colors.map(([key,c])=><button key={c} type="button" title={t(`drawing_${key}`)} aria-label={t(`drawing_${key}`)} aria-pressed={color===c} className={color===c?'active':''} style={{background:c}} onClick={()=>setColor(c)}>{color===c&&<Check size={15}/>}</button>)}</div>
   <label><input aria-label={t('drawing_width')} type="range" min="2" max="12" value={width} onChange={e=>setWidth(+e.target.value)}/></label>
   <div className="histBtns"><button title={t('drawing_undo')} aria-label={t('drawing_undo')} disabled={!shapes.length||busy} onClick={()=>{setRedo(r=>[...r,shapes.at(-1)!]);setShapes(s=>s.slice(0,-1));setDirty(true)}}><Undo2 size={18}/></button><button title={t('drawing_redo')} aria-label={t('drawing_redo')} disabled={!redo.length||busy} onClick={()=>{setShapes(s=>[...s,redo.at(-1)!]);setRedo(r=>r.slice(0,-1));setDirty(true)}}><Redo2 size={18}/></button><button title={t('drawing_clear')} aria-label={t('drawing_clear')} disabled={busy||!shapes.length} onClick={()=>{setShapes([]);setRedo([]);setDirty(true)}}><Trash2 size={18}/></button></div>
   <button className="drawSave" title={t('drawing_save')} aria-label={t('drawing_save')} disabled={loading||busy||!dirty} onClick={()=>void save()}>{busy?<span>...</span>:<Save size={19}/>}</button><span className="drawingState" role="status">{t(dirty?'drawing_unsaved':'drawing_saved')} · {t('drawing_frame')} {formatTime(frame)}</span>
  </div>}{error&&<div className="drawingError" role="alert">{error}</div>}
 </div>
}

function ShapeView({shape:s,height}:{shape:Shape;height:number}){
 if(s.visible===false)return null;
 const x=(n:number)=>n*1000,y=(n:number)=>n*height,common={stroke:s.color,strokeWidth:s.lineWidth||5,opacity:s.opacity??1};
 if(['polygon','pen','freehand','player-trail'].includes(s.type)){const points=s.points?.map(p=>`${x(p[0])},${y(p[1])}`).join(' ');return s.type==='polygon'?<polygon points={points} fill={s.fill||'none'} {...common} strokeLinejoin="round"/>:<polyline points={points} fill="none" {...common} strokeLinecap="round" strokeLinejoin="round"/>}
 if(s.type==='arrow'){const dx=x(s.x2-s.x1),dy=y(s.y2-s.y1),angle=Math.atan2(dy,dx),head=Math.min(Math.hypot(dx,dy)*.08,25);return <g {...common} fill="none"><line x1={x(s.x1)} y1={y(s.y1)} x2={x(s.x2)} y2={y(s.y2)}/><path d={`M ${x(s.x2)-head*Math.cos(angle-.5)} ${y(s.y2)-head*Math.sin(angle-.5)} L ${x(s.x2)} ${y(s.y2)} L ${x(s.x2)-head*Math.cos(angle+.5)} ${y(s.y2)-head*Math.sin(angle+.5)}`}/></g>}
 if(['circle','ellipse','spotlight'].includes(s.type))return <ellipse cx={x((s.x1+s.x2)/2)} cy={y((s.y1+s.y2)/2)} rx={Math.abs(x(s.x2-s.x1))/2} ry={Math.abs(y(s.y2-s.y1))/2} fill={s.fill||'none'} {...common}/>;
 if(s.type==='rectangle')return <rect x={x(Math.min(s.x1,s.x2))} y={y(Math.min(s.y1,s.y2))} width={Math.abs(x(s.x2-s.x1))} height={Math.abs(y(s.y2-s.y1))} fill={s.fill||'none'} {...common}/>;
 if(['text','player-label'].includes(s.type))return <text x={x(s.x1)} y={y(s.y1)} fill={s.color} opacity={s.opacity} fontSize="36">{s.text}</text>;
 return <line x1={x(s.x1)} y1={y(s.y1)} x2={x(s.x2)} y2={y(s.y2)} {...common}/>;
}
