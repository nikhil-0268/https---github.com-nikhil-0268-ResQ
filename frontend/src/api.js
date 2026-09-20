const DB='resq-local-v1';
function database(){return new Promise((resolve,reject)=>{const q=indexedDB.open(DB,1);q.onupgradeneeded=()=>{q.result.createObjectStore('queue',{keyPath:'id'});q.result.createObjectStore('cache')};q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error)})}
async function operation(store,mode,fn){const db=await database();return new Promise((resolve,reject)=>{const tx=db.transaction(store,mode);let result;const request=fn(tx.objectStore(store));request.onsuccess=()=>result=request.result;tx.oncomplete=()=>{db.close();resolve(result)};tx.onerror=()=>{db.close();reject(tx.error)}})}
export const cacheGet=key=>operation('cache','readonly',s=>s.get(key));
export const cacheSet=(key,value)=>operation('cache','readwrite',s=>s.put(value,key));
export const clearCache=()=>operation('cache','readwrite',s=>s.clear());
export const pending=()=>operation('queue','readonly',s=>s.getAll());
export const removePending=id=>operation('queue','readwrite',s=>s.delete(id));
export function credentials(){try{return JSON.parse(sessionStorage.getItem('resq-session'))}catch{return null}}
export async function api(path,options={}){
 const session=credentials();const headers={...options.headers}; if(session)headers['X-Responder-Code']=session.code;
 if(options.body && !(options.body instanceof FormData))headers['Content-Type']='application/json';
 let response;try{response=await fetch('/api'+path,{...options,headers,signal:AbortSignal.timeout(45000)})}catch(e){e.network=true;throw e}
 if(!response.ok){let body;try{body=await response.json()}catch{};const e=new Error(typeof body?.detail==='string'?body.detail:JSON.stringify(body?.detail||'Request failed'));e.status=response.status;e.retryable=response.status>=500||response.status===429;throw e}
 return options.blob?response.blob():response.json();
}
export async function mutate(path,body,method='POST'){
 const id=crypto.randomUUID();const isForm=body instanceof FormData;
 if(isForm)body.set('client_id',id);else body={...body,client_id:id};
 const item={id,path,method,form:isForm,body:isForm?[...body.entries()]:body,owner:path==='/reports'?null:credentials()?.name,created:Date.now()};
 await operation('queue','readwrite',s=>s.put(item));
 try{const result=await send(item);await removePending(id);return result}catch(e){if(e.network||e.retryable)return {queued:true};await removePending(id);throw e}
}
function send(item){return api(item.path,{method:item.method,body:item.form?toForm(item.body):JSON.stringify(item.body)})}
function toForm(entries){const body=new FormData();entries.forEach(([k,v])=>body.append(k,v));return body}
let syncing=false;
export async function sync(){if(syncing)return;syncing=true;try{for(const item of (await pending()).sort((a,b)=>a.created-b.created)){if(item.owner && credentials()?.name!==item.owner)continue;try{await send(item);await removePending(item.id)}catch(e){if(e.network||e.retryable)break;throw new Error('Saved change needs attention: '+e.message)}}}finally{syncing=false}}
