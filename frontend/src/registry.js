export const STATUSES={safe:'Safe',missing:'Missing',needs_medical:'Needs medical attention',in_shelter:'In shelter',relocated:'Relocated'};
export function registryView(base={people:[],shelters:[]},queue=[],owner){
 const people=new Map((base.people||[]).map(p=>[p.id,{...p}]));
 const shelters=new Map((base.shelters||[]).map(s=>[s.id,{...s}]));
 const edits=queue.filter(q=>q.owner===owner&&(q.path==='/people'||q.path==='/shelters'||/^\/people\/[^/]+\/check-in$/.test(q.path))).sort((a,b)=>a.created-b.created);
 for(const q of edits){const b=q.body;const meta={pending:true,pending_error:q.error||null};
  if(q.path==='/shelters'&&!shelters.has(b.id))shelters.set(b.id,{...b,created_at:q.created/1000,...meta});
  if(q.path==='/people'&&!people.has(b.id))people.set(b.id,{...b,version:1,created_at:q.created/1000,updated_at:q.created/1000,...meta});
  if(q.path.endsWith('/check-in')){const id=q.path.split('/')[2],p=people.get(id);if(p){
   if(q.error||p.version>b.expected_version){p.pending=true;p.pending_error=q.error||'Profile changed on the server; review the saved change.';continue}
   const changed=p.status!==b.status||p.shelter_id!==b.shelter_id||b.note?.trim();people.set(id,{...p,status:b.status,shelter_id:b.shelter_id,version:p.version+(changed?1:0),updated_at:q.created/1000,...meta});
  }}
 }
 const ps=[...people.values()].sort((a,b)=>b.updated_at-a.updated_at);
 const sites=[...shelters.values()].map(s=>{const current=ps.filter(p=>p.shelter_id===s.id).length;return {...s,current_count:current,available:Math.max(0,s.max_capacity-current)}});
 return {people:ps,shelters:sites,pending:edits,as_of:base.as_of,counts:{registered:ps.length,at_sites:ps.filter(p=>p.shelter_id).length,needs_medical:ps.filter(p=>p.status==='needs_medical').length,missing:ps.filter(p=>p.status==='missing').length}};
}
export function parsePersonCode(value){const code=value.trim().replace(/^RESQ:/i,'').toUpperCase();return /^P-[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}$/.test(code)?code:null}
