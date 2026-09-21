export function filterQueue(items,{tab='all',priority='all',status='open',query=''}={}) {
 const result=items.filter(i=>(tab==='all'||tab==='location'||(tab==='search'?i.is_search_relevant:!i.is_search_relevant))&&(priority==='all'||i.priority===priority)&&(status==='all'||(status==='open'?!['resolved','false_alarm'].includes(i.status):i.status===status))&&(i.place_name+' '+i.primary_type).toLowerCase().includes(query.toLowerCase()));
 return tab==='all'?result.sort((a,b)=>b.last_signal_at-a.last_signal_at):result;
}
