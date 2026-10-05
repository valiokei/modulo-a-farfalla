export async function api<T=any>(path:string,init:RequestInit={}):Promise<T>{
  const r=await fetch(`/api${path}`,{credentials:'include',...init,headers:{...(init.body instanceof FormData?{}:{'Content-Type':'application/json'}),...init.headers}})
  if(!r.ok){
    const detail=(await r.json().catch(()=>null))?.detail
    const message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map((e:any)=>[Array.isArray(e?.loc)?e.loc.filter((x:unknown)=>x!=='body').join('.'):'' ,e?.msg].filter(Boolean).join(': ')).filter(Boolean).join(' · '):''
    throw new Error(message||`Request failed (${r.status})`)
  }
  if(r.status===204)return undefined as T
  return r.json()
}
export const post=(p:string,b:unknown)=>api(p,{method:'POST',body:JSON.stringify(b)});
export const patch=(p:string,b:unknown)=>api(p,{method:'PATCH',body:JSON.stringify(b)});
export function formatTime(n:number){const s=Math.max(0,Math.floor(n));return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`}
export function parseTime(value:string):number|null{const parts=value.trim().split(':');if(!parts.length||parts.length>3)return null;const nums=parts.map(p=>p.trim());if(nums.some(p=>!/^\d{1,4}$/.test(p)))return null;const vals=nums.map(Number);if(nums.length>1&&vals[vals.length-1]>59)return null;if(nums.length>2&&vals[vals.length-2]>59)return null;return vals.reduce((acc,n)=>acc*60+n,0)}
