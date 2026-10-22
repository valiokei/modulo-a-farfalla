import {useEffect,useRef,useState} from 'react';
import type {PointerEvent,MouseEvent} from 'react';
import {Check,ClipboardPaste,Copy,MousePointer2,MoveUpRight,Pencil,Pentagon,Redo2,Save,Trash2,Type,Undo2,X} from 'lucide-react';
import {api,post,formatTime} from './api';
import type {Event,Shape} from './types';
import {t} from './i18n';
import './review.css';

type Annotation={id:string;timestamp:number;shapes:Shape[]};
type Box={x1:number;y1:number;x2:number;y2:number;cx:number;cy:number;rotation:number};
type Drag={mode:'move'|'resize'|'rotate';index:number;start:[number,number];orig:Shape;pointerId:number;moved:boolean};
// Module-level so a copied element can be pasted into the notes of another event.
let clipboard:Shape|undefined;
let measureCtx:CanvasRenderingContext2D|null|undefined;
const FONT="'DM Sans',sans-serif";
// Width of the text in SVG units (1000 across), measured like the SVG renders it.
const measure=(text:string,size:number)=>{if(measureCtx===undefined)measureCtx=document.createElement('canvas').getContext('2d');if(!measureCtx)return text.length*size*.55;measureCtx.font=`700 ${size}px ${FONT}`;return measureCtx.measureText(text).width};
const isText=(s:Shape)=>['text','player-label'].includes(s.type);
const hasPoints=(s:Shape)=>['pen','freehand','player-trail','polygon'].includes(s.type);
const clamp=(n:number)=>Math.min(1,Math.max(0,n));
// Normalised box of a shape; text boxes come from x2/y2 or (older notes) from the measured text.
function shapeBox(s:Shape,height:number):Box{
 if(isText(s)){const size=s.size||36,x1=s.x1,y1=s.y1,known=s.x2>s.x1&&s.y2>s.y1,x2=known?s.x2:x1+measure(s.text||'',size)/1000,y2=known?s.y2:y1+size/height;return{x1,y1,x2,y2,cx:(x1+x2)/2,cy:(y1+y2)/2,rotation:s.rotation||0}}
 const xs=hasPoints(s)&&s.points?.length?s.points.map(p=>p[0]):[s.x1,s.x2],ys=hasPoints(s)&&s.points?.length?s.points.map(p=>p[1]):[s.y1,s.y2];
 const x1=Math.min(...xs),x2=Math.max(...xs),y1=Math.min(...ys),y2=Math.max(...ys);return{x1,y1,x2,y2,cx:(x1+x2)/2,cy:(y1+y2)/2,rotation:0};
}
// Screen-aligned bounds of a (possibly rotated) box, normalised.
function bounds(b:Box,height:number){if(!b.rotation)return b;const a=b.rotation*Math.PI/180,cx=b.cx*1000,cy=b.cy*height,pts=[[b.x1,b.y1],[b.x2,b.y1],[b.x1,b.y2],[b.x2,b.y2]].map(([x,y])=>rotateAround(x*1000,y*height,cx,cy,a)),xs=pts.map(p=>p[0]/1000),ys=pts.map(p=>p[1]/height);return{...b,x1:Math.min(...xs),x2:Math.max(...xs),y1:Math.min(...ys),y2:Math.max(...ys)}}
// Apply f to every coordinate of the shape (in SVG units, so rotation/scale stay isotropic).
function mapPoints(s:Shape,height:number,f:(x:number,y:number)=>[number,number]):Shape{const g=(x:number,y:number):[number,number]=>{const[a,b]=f(x*1000,y*height);return[clamp(a/1000),clamp(b/height)]};const[x1,y1]=g(s.x1,s.y1),[x2,y2]=g(s.x2,s.y2);return{...s,x1,y1,x2,y2,...(s.points?{points:s.points.map(p=>g(p[0],p[1]))}:{})}}
const rotateAround=(x:number,y:number,cx:number,cy:number,a:number):[number,number]=>[cx+(x-cx)*Math.cos(a)-(y-cy)*Math.sin(a),cy+(x-cx)*Math.sin(a)+(y-cy)*Math.cos(a)];
const canRotate=(s:Shape)=>isText(s)||hasPoints(s)||['arrow','line'].includes(s.type);
// Handles in SVG units: resize at the bottom-right corner, rotate above the top edge (both follow the rotation).
function handles(b:Box,height:number){const cx=b.cx*1000,cy=b.cy*height,a=b.rotation*Math.PI/180;return{resize:rotateAround(b.x2*1000+6,b.y2*height+6,cx,cy,a),rotate:rotateAround(cx,b.y1*height-34,cx,cy,a),top:rotateAround(cx,b.y1*height-6,cx,cy,a)}}

export function DrawingOverlay({event,current,aspect=16/9,onDirty,open,setOpen,captureFrame,showFrame,reveal}:{event:Event;current:number;aspect?:number;onDirty?:(value:boolean)=>void;open:boolean;setOpen:(value:boolean)=>void;captureFrame:()=>number;showFrame:(time:number)=>void;reveal?:number}){
 const [tool,setTool]=useState('pen'),[shapes,setShapes]=useState<Shape[]>([]),[past,setPast]=useState<Shape[][]>([]),[future,setFuture]=useState<Shape[][]>([]),[draft,setDraft]=useState<Shape>(),[color,setColor]=useState('#ffdf36'),[width,setWidth]=useState(5),[dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[frame,setFrame]=useState(event.timestamp);
 const [loading,setLoading]=useState(true),[typing,setTyping]=useState<{x:number;y:number;text:string;size:number;index?:number}>(),[selected,setSelected]=useState<number>(),[pasteReady,setPasteReady]=useState(!!clipboard);
 const root=useRef<HTMLDivElement>(null),stroke=useRef<Shape|undefined>(undefined),pointer=useRef<number|undefined>(undefined),annotationId=useRef<string|undefined>(undefined),drag=useRef<Drag|undefined>(undefined);
 const height=1000/aspect;
 useEffect(()=>{onDirty?.(dirty)},[dirty,onDirty]);
 useEffect(()=>{let active=true;setLoading(true);annotationId.current=undefined;stroke.current=undefined;pointer.current=undefined;drag.current=undefined;setDraft(undefined);setShapes([]);setPast([]);setFuture([]);setSelected(undefined);setDirty(false);setError('');setTyping(undefined);api<Annotation[]>(`/events/${event.id}/annotations`).then(rows=>{if(active){annotationId.current=rows[0]?.id;setShapes(rows[0]?.shapes||[]);setFrame(rows[0]?.timestamp??event.timestamp)}}).catch(e=>{if(active)setError((e as Error).message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[event.id]);
 useEffect(()=>{if(!open||loading||error)return;if(annotationId.current||dirty){showFrame(frame)}else{const captured=captureFrame();setFrame(captured);showFrame(captured)}},[open,loading]);
 useEffect(()=>{if(!open){setSelected(undefined);setTyping(undefined)}},[open]);
 // Coming back to an event (timeline, list, stats): pause on the annotated frame once the note is loaded.
 const revealed=useRef<number|undefined>(undefined);
 useEffect(()=>{if(reveal===undefined||reveal===revealed.current||loading)return;revealed.current=reveal;if(annotationId.current&&shapes.length)showFrame(frame)},[reveal,loading]);
 // Every change goes through commit() so undo/redo also covers moves, deletions and pastes.
 const commit=(next:Shape[],before:Shape[]=shapes)=>{setPast(p=>[...p.slice(-99),before]);setFuture([]);setShapes(next);setDirty(true)};
 const point=(e:{clientX:number;clientY:number}):[number,number]=>{const r=root.current!.getBoundingClientRect();return[clamp((e.clientX-r.left)/r.width),clamp((e.clientY-r.top)/r.height)]};
 const hit=([x,y]:[number,number])=>{for(let i=shapes.length-1;i>=0;i--){const s=shapes[i];if(s.visible===false)continue;const b=shapeBox(s,height);const[px,py]=rotateAround(x*1000,y*height,b.cx*1000,b.cy*height,-b.rotation*Math.PI/180),pad=14;if(px>=b.x1*1000-pad&&px<=b.x2*1000+pad&&py>=b.y1*height-pad&&py<=b.y2*height+pad)return i}return undefined};
 const handleAt=([x,y]:[number,number])=>{if(selected===undefined||!shapes[selected])return;const s=shapes[selected],h=handles(shapeBox(s,height),height),near=(p:[number,number])=>Math.hypot(p[0]-x*1000,p[1]-y*height)<16;if(near(h.resize))return'resize' as const;if(canRotate(s)&&near(h.rotate))return'rotate' as const};
 const startDrag=(e:PointerEvent<HTMLDivElement>,mode:Drag['mode'],index:number,p:[number,number])=>{const s=shapes[index],b=shapeBox(s,height);drag.current={mode,index,start:p,orig:isText(s)?{...s,x2:b.x2,y2:b.y2}:s,pointerId:e.pointerId,moved:false};pointer.current=e.pointerId;e.currentTarget.setPointerCapture(e.pointerId)};
 const down=(e:PointerEvent<HTMLDivElement>)=>{if(!open||busy||loading||error||!e.isPrimary||e.button!==0||(e.target as HTMLElement).closest?.('.drawTools,.drawToggle,.drawTextInput,.drawItemBar'))return;e.preventDefault();e.stopPropagation();showFrame(frame);const p=point(e);
  const handle=handleAt(p);if(handle){startDrag(e,handle,selected!,p);return}
  // Any tool: grab the selected element; the text tool also grabs an existing text instead of starting a new one.
  {const index=hit(p);if(index!==undefined&&(index===selected||(tool==='text'&&isText(shapes[index])))){commitText();setSelected(index);startDrag(e,'move',index,p);return}}
  if(tool==='select'){commitText();const index=hit(p);setSelected(index);if(index!==undefined)startDrag(e,'move',index,p);return}
  setSelected(undefined);const[x,y]=p;if(tool==='text'){commitText();setTyping({x,y,text:'',size:textSize});return}
  const shape:Shape={type:tool,x1:x,y1:y,x2:x,y2:y,color,lineWidth:width,fill:tool==='polygon'?color+'55':'none',opacity:.95,visible:true,start:event.start,end:event.end,...(['pen','polygon'].includes(tool)?{points:[[x,y] as [number,number]]}:{})};stroke.current=shape;pointer.current=e.pointerId;setDraft(shape);e.currentTarget.setPointerCapture(e.pointerId)};
 const dragTo=(p:[number,number])=>{const d=drag.current!,o=d.orig,b=shapeBox(o,height),cx=b.cx*1000,cy=b.cy*height;let next:Shape;
  if(d.mode==='move'){const v=bounds(b,height),dx=Math.max(-v.x1,Math.min(1-v.x2,p[0]-d.start[0])),dy=Math.max(-v.y1,Math.min(1-v.y2,p[1]-d.start[1]));next=mapPoints(o,height,(x,y)=>[x+dx*1000,y+dy*height])}
  else if(d.mode==='resize'){const h=handles(b,height).resize,k0=Math.hypot(p[0]*1000-cx,p[1]*height-cy)/Math.max(1,Math.hypot(h[0]-cx,h[1]-cy));const k=isText(o)?Math.min(400,Math.max(8,(o.size||36)*k0))/(o.size||36):Math.max(.1,k0);next={...mapPoints(o,height,(x,y)=>[cx+(x-cx)*k,cy+(y-cy)*k]),...(isText(o)?{size:Math.round((o.size||36)*k*10)/10}:{})}}
  else{const a=Math.atan2(p[1]*height-cy,p[0]*1000-cx)-Math.atan2(d.start[1]*height-cy,d.start[0]*1000-cx);if(isText(o)){let r=((o.rotation||0)+a*180/Math.PI)%360;r=(r+360)%360;const snap=[0,90,180,270,360].find(v=>Math.abs(v-r)<4);next={...o,rotation:Math.round((snap??r)%360)}}else next=mapPoints(o,height,(x,y)=>rotateAround(x,y,cx,cy,a))}
  if(!d.moved){d.moved=true;setPast(h=>[...h.slice(-99),shapes]);setFuture([])}
  setShapes(s=>s.map((shape,i)=>i===d.index?next:shape));setDirty(true)};
 const move=(e:PointerEvent<HTMLDivElement>)=>{if(pointer.current!==e.pointerId)return;if(drag.current){e.preventDefault();dragTo(point(e));return}if(!stroke.current)return;e.preventDefault();const[x,y]=point(e),old=stroke.current;const next={...old,x2:x,y2:y,points:old.points&&old.points.length<4096?[...old.points,[x,y] as [number,number]]:old.points};stroke.current=next;setDraft(next)};
 const finish=(e:PointerEvent<HTMLDivElement>)=>{if(pointer.current!==e.pointerId)return;e.preventDefault();if(drag.current){drag.current=undefined;pointer.current=undefined;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);return}move(e);const completed=stroke.current;stroke.current=undefined;pointer.current=undefined;setDraft(undefined);if(completed)commit([...shapes,completed]);if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId)};
 const cancel=(e:PointerEvent<HTMLDivElement>)=>{if(pointer.current===e.pointerId){stroke.current=undefined;pointer.current=undefined;drag.current=undefined;setDraft(undefined)}};
 // Text notes: click places the box, Enter (or clicking elsewhere) keeps it, Esc discards it; double click edits.
 const textSize=12+width*4;
 const commitText=()=>{const cur=typing,text=cur?.text.trim().slice(0,200);setTyping(undefined);if(!cur)return;
  if(cur.index!==undefined){const old=shapes[cur.index];if(!old)return;if(!text){commit(shapes.filter((_,i)=>i!==cur.index));setSelected(undefined);return}if(text===old.text)return;const size=old.size||36,b=shapeBox(old,height),w=measure(text,size)/1000,c=b.cx;commit(shapes.map((s,i)=>i===cur.index?{...s,text,x1:clamp(c-w/2),x2:clamp(c+w/2)}:s));return}
  if(!text)return;const size=cur.size;commit([...shapes,{type:'text',x1:cur.x,y1:cur.y,x2:clamp(cur.x+measure(text,size)/1000),y2:clamp(cur.y+size/height),text,size,rotation:0,color,lineWidth:width,opacity:1,visible:true,start:event.start,end:event.end}]);setSelected(shapes.length)};
 const editText=(e:MouseEvent<HTMLDivElement>)=>{if(!open||(e.target as HTMLElement).closest?.('.drawTools,.drawToggle,.drawTextInput,.drawItemBar'))return;const index=hit(point(e));if(index===undefined||!isText(shapes[index]))return;const s=shapes[index];setSelected(index);setTyping({x:s.x1,y:s.y1,text:s.text||'',size:s.size||36,index})};
 const remove=(index=selected)=>{if(index===undefined)return;commit(shapes.filter((_,i)=>i!==index));setSelected(undefined)};
 const copy=(index=selected)=>{if(index===undefined||!shapes[index])return;clipboard=structuredClone(shapes[index]);setPasteReady(true)};
 const paste=()=>{if(!clipboard)return;const b=shapeBox(clipboard,height),dx=b.x2+.03<=1?.03:-.03,dy=b.y2+.03<=1?.03:-.03;const pasted={...mapPoints(clipboard,height,(x,y)=>[x+dx*1000,y+dy*height]),start:event.start,end:event.end,visible:true};clipboard=structuredClone(pasted);commit([...shapes,pasted]);setSelected(shapes.length)};
 const undo=()=>{if(!past.length)return;setFuture(f=>[...f,shapes]);setShapes(past.at(-1)!);setPast(p=>p.slice(0,-1));setSelected(undefined);setDirty(true)};
 const redoIt=()=>{if(!future.length)return;setPast(p=>[...p,shapes]);setShapes(future.at(-1)!);setFuture(f=>f.slice(0,-1));setSelected(undefined);setDirty(true)};
 const contextMenu=(e:MouseEvent<HTMLDivElement>)=>{if(!open)return;e.preventDefault();if((e.target as HTMLElement).closest?.('.drawTools,.drawItemBar'))return;commitText();const index=hit(point(e));if(index!==undefined){setSelected(index);setTool('select')}};
 const chooseColor=(c:string)=>{setColor(c);if(selected!==undefined&&shapes[selected]&&shapes[selected].color!==c){const s=shapes[selected];commit(shapes.map((x,i)=>i===selected?{...s,color:c,...(s.type==='polygon'?{fill:c+'55'}:{})}:x))}};
 useEffect(()=>{if(!open)return;const onKey=(e:KeyboardEvent)=>{if(typing||(e.target as HTMLElement).closest?.('input,textarea,select,[contenteditable=true]'))return;const mod=e.ctrlKey||e.metaKey,k=e.key.toLowerCase();let done=true;
  if((e.key==='Delete'||e.key==='Backspace')&&selected!==undefined)remove();else if(mod&&k==='c'&&selected!==undefined)copy();else if(mod&&k==='v'&&clipboard)paste();else if(mod&&k==='d'&&selected!==undefined){copy();paste()}else if(mod&&k==='z'&&!e.shiftKey)undo();else if(mod&&(k==='y'||(k==='z'&&e.shiftKey)))redoIt();else if(e.key==='Escape'&&selected!==undefined)setSelected(undefined);else if(e.key==='Enter'&&selected!==undefined&&isText(shapes[selected])){const s=shapes[selected];setTyping({x:s.x1,y:s.y1,text:s.text||'',size:s.size||36,index:selected})}else done=false;
  if(done){e.preventDefault();e.stopPropagation()}};window.addEventListener('keydown',onKey,true);return()=>window.removeEventListener('keydown',onKey,true)});
 const save=async()=>{setBusy(true);setError('');try{commitText();const payload={timestamp:frame,start:event.start,end:event.end,coordinate_mode:'screen',shapes};const row=annotationId.current?await api<Annotation>(`/annotations/${annotationId.current}`,{method:'PUT',body:JSON.stringify(payload)}):await post(`/events/${event.id}/annotations`,payload);annotationId.current=row.id;setDirty(false)}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const tools=[['select',MousePointer2],['pen',Pencil],['polygon',Pentagon],['arrow',MoveUpRight],['text',Type]] as const;
 const colors=[['yellow','#ffdf36'],['orange','#ff8c42'],['blue','#42d6ff'],['green','#7ee07e'],['pink','#ff5b9a']];
 const sel=open&&selected!==undefined&&shapes[selected]&&typing?.index!==selected?shapes[selected]:undefined,selBox=sel?shapeBox(sel,height):undefined,barBox=selBox&&bounds(selBox,height);
 const px=(n:number)=>n*(root.current?.clientWidth||1000)/1000;
 return <div ref={root} className={`drawing ${open?'open':''} tool-${tool}`} onPointerDown={down} onPointerMove={move} onPointerUp={finish} onPointerCancel={cancel} onLostPointerCapture={cancel} onDoubleClick={editText} onContextMenu={contextMenu} onDragStart={e=>e.preventDefault()}>
  <button className="drawToggle" type="button" disabled={!open&&(loading||!!error)} onClick={()=>setOpen(!open)} title={t(open?'drawing_close':'drawing_open')} aria-label={t(open?'drawing_close':'drawing_open')} aria-pressed={open}>{open?<X size={20}/>:<Pencil size={20}/>}</button>
  {open&&typing&&<input className="drawTextInput" autoFocus maxLength={200} value={typing.text} placeholder={t('drawing_text_placeholder')} aria-label={t('drawing_text')} style={{left:`${typing.x*100}%`,top:`${typing.y*100}%`,color:typing.index!==undefined?shapes[typing.index]?.color:color,fontSize:`${px(typing.size)}px`}} onPointerDown={e=>e.stopPropagation()} onDoubleClick={e=>e.stopPropagation()} onChange={e=>setTyping({...typing,text:e.target.value})} onKeyDown={e=>{e.stopPropagation();if(e.key==='Enter'){e.preventDefault();commitText()}else if(e.key==='Escape'){e.preventDefault();setTyping(undefined)}}} onBlur={commitText}/>}
  <svg viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none" aria-label={t('drawing_canvas')}>{[...shapes,...(draft?[draft]:[])].map((s,i)=>({s,i})).filter(({s,i})=>i!==typing?.index&&(open||((s.start??event.start)<=current&&(s.end??event.end)>current))).map(({s,i})=><ShapeView key={i} shape={s} height={height}/>)}
   {sel&&selBox&&<Selection box={selBox} height={height} rotatable={canRotate(sel)}/>}</svg>
  {sel&&barBox&&<div className={`drawItemBar ${barBox.y1<.2?'below':''}`} role="toolbar" aria-label={t('drawing_item_actions')} style={{left:`${Math.max(0,Math.min(barBox.x1,.8))*100}%`,top:`${(barBox.y1<.2?Math.min(barBox.y2,.88):barBox.y1)*100}%`}} onPointerDown={e=>e.stopPropagation()} onDoubleClick={e=>e.stopPropagation()}>
   <button type="button" title={t('drawing_copy')} aria-label={t('drawing_copy')} onClick={()=>copy()}><Copy size={15}/></button>
   <button type="button" title={t('drawing_paste')} aria-label={t('drawing_paste')} disabled={!pasteReady} onClick={paste}><ClipboardPaste size={15}/></button>
   {isText(sel)&&<button type="button" title={t('drawing_edit_text')} aria-label={t('drawing_edit_text')} onClick={()=>setTyping({x:sel.x1,y:sel.y1,text:sel.text||'',size:sel.size||36,index:selected})}><Type size={15}/></button>}
   <button type="button" className="danger" title={t('drawing_delete')} aria-label={t('drawing_delete')} onClick={()=>remove()}><Trash2 size={15}/></button>
  </div>}
  {open&&<div className="drawTools compact" onPointerDown={e=>e.stopPropagation()} onDoubleClick={e=>e.stopPropagation()}>
   <div className="toolBtns">{tools.map(([key,Icon])=><button key={key} type="button" title={t(`drawing_${key}`)} aria-label={t(`drawing_${key}`)} aria-pressed={tool===key} className={tool===key?'active':''} onClick={()=>{commitText();setTool(key);if(key!=='select')setSelected(undefined)}}><Icon size={19}/></button>)}</div>
   <div className="colorBtns">{colors.map(([key,c])=><button key={c} type="button" title={t(`drawing_${key}`)} aria-label={t(`drawing_${key}`)} aria-pressed={color===c} className={color===c?'active':''} style={{background:c}} onClick={()=>chooseColor(c)}>{color===c&&<Check size={15}/>}</button>)}</div>
   <label><input aria-label={t('drawing_width')} type="range" min="2" max="12" value={width} onChange={e=>setWidth(+e.target.value)}/></label>
   <div className="histBtns"><button title={t('drawing_undo')} aria-label={t('drawing_undo')} disabled={!past.length||busy} onClick={undo}><Undo2 size={18}/></button><button title={t('drawing_redo')} aria-label={t('drawing_redo')} disabled={!future.length||busy} onClick={redoIt}><Redo2 size={18}/></button><button title={t('drawing_paste')} aria-label={t('drawing_paste')} disabled={!pasteReady||busy} onClick={paste}><ClipboardPaste size={18}/></button><button title={t('drawing_clear')} aria-label={t('drawing_clear')} disabled={busy||!shapes.length} onClick={()=>{commit([]);setSelected(undefined)}}><Trash2 size={18}/></button></div>
   <button className="drawSave" title={t('drawing_save')} aria-label={t('drawing_save')} disabled={loading||busy||!dirty} onClick={()=>void save()}>{busy?<span>...</span>:<Save size={19}/>}</button>{sel&&<span className="drawHint">{t('drawing_move_hint')}</span>}<span className="drawingState" role="status">{t(dirty?'drawing_unsaved':'drawing_saved')} · {t('drawing_frame')} {formatTime(frame)}</span>
  </div>}{error&&<div className="drawingError" role="alert">{error}</div>}
 </div>
}

function Selection({box:b,height,rotatable}:{box:Box;height:number;rotatable:boolean}){
 const pad=6,h=handles(b,height),x=b.x1*1000-pad,y=b.y1*height-pad,w=(b.x2-b.x1)*1000+2*pad,hh=(b.y2-b.y1)*height+2*pad;
 return <g className="drawSelection" pointerEvents="none"><rect x={x} y={y} width={w} height={hh} transform={`rotate(${b.rotation} ${b.cx*1000} ${b.cy*height})`} fill="none" stroke="#ffffff" strokeWidth={1.5} strokeDasharray="6 4" vectorEffect="non-scaling-stroke"/>
  {rotatable&&<><line x1={h.top[0]} y1={h.top[1]} x2={h.rotate[0]} y2={h.rotate[1]} stroke="#ffffff" strokeWidth={1.5} vectorEffect="non-scaling-stroke"/><circle className="rotateHandle" cx={h.rotate[0]} cy={h.rotate[1]} r={7} fill="#176e5b" stroke="#ffffff" strokeWidth={2} vectorEffect="non-scaling-stroke"/></>}
  <rect className="resizeHandle" x={h.resize[0]-6} y={h.resize[1]-6} width={12} height={12} transform={`rotate(${b.rotation} ${h.resize[0]} ${h.resize[1]})`} fill="#ffffff" stroke="#176e5b" strokeWidth={2} vectorEffect="non-scaling-stroke"/></g>
}

function ShapeView({shape:s,height}:{shape:Shape;height:number}){
 if(s.visible===false)return null;
 const x=(n:number)=>n*1000,y=(n:number)=>n*height,common={stroke:s.color,strokeWidth:s.lineWidth||5,opacity:s.opacity??1};
 if(['polygon','pen','freehand','player-trail'].includes(s.type)){const points=s.points?.map(p=>`${x(p[0])},${y(p[1])}`).join(' ');return s.type==='polygon'?<polygon points={points} fill={s.fill||'none'} {...common} strokeLinejoin="round"/>:<polyline points={points} fill="none" {...common} strokeLinecap="round" strokeLinejoin="round"/>}
 if(s.type==='arrow'){const dx=x(s.x2-s.x1),dy=y(s.y2-s.y1),angle=Math.atan2(dy,dx),head=Math.min(Math.hypot(dx,dy)*.08,25);return <g {...common} fill="none"><line x1={x(s.x1)} y1={y(s.y1)} x2={x(s.x2)} y2={y(s.y2)}/><path d={`M ${x(s.x2)-head*Math.cos(angle-.5)} ${y(s.y2)-head*Math.sin(angle-.5)} L ${x(s.x2)} ${y(s.y2)} L ${x(s.x2)-head*Math.cos(angle+.5)} ${y(s.y2)-head*Math.sin(angle+.5)}`}/></g>}
 if(['circle','ellipse','spotlight'].includes(s.type))return <ellipse cx={x((s.x1+s.x2)/2)} cy={y((s.y1+s.y2)/2)} rx={Math.abs(x(s.x2-s.x1))/2} ry={Math.abs(y(s.y2-s.y1))/2} fill={s.fill||'none'} {...common}/>;
 if(s.type==='rectangle')return <rect x={x(Math.min(s.x1,s.x2))} y={y(Math.min(s.y1,s.y2))} width={Math.abs(x(s.x2-s.x1))} height={Math.abs(y(s.y2-s.y1))} fill={s.fill||'none'} {...common}/>;
 // x1/y1 is the top-left corner of the text box, rotation turns it around the box centre; telestration.py matches both.
 if(isText(s)){const size=s.size||36,b=shapeBox(s,height);return <text x={x(s.x1)} y={y(s.y1)+size*.8} transform={b.rotation?`rotate(${b.rotation} ${b.cx*1000} ${b.cy*height})`:undefined} fill={s.color} opacity={s.opacity} fontSize={size} fontWeight="700" fontFamily={FONT} stroke="#000000" strokeWidth={size/9} strokeLinejoin="round" paintOrder="stroke">{s.text}</text>}
 return <line x1={x(s.x1)} y1={y(s.y1)} x2={x(s.x2)} y2={y(s.y2)} {...common}/>;
}
