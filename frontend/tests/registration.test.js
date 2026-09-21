import test from 'node:test';
import assert from 'node:assert/strict';
import QRCode from 'qrcode';
import jsQR from 'jsqr';
import {filterQueue} from '../src/queue.js';
import {registryView,parsePersonCode} from '../src/registry.js';
const person='P-12345678-1234-1234-1234-123456789ABC';
const edit=(path,body,created,error)=>({path,body,created,error,owner:'Tester'});
test('all incoming includes newest unknown and medical reports without disturbing search ranking',()=>{
 const items=[{id:1,place_name:'Kalimati',primary_type:'building_collapse',status:'pending',is_search_relevant:true,last_signal_at:1},{id:2,place_name:'Boudha',primary_type:'unknown',status:'pending',last_signal_at:3},{id:3,place_name:'Patan',primary_type:'medical_need',status:'pending',last_signal_at:2}];
 assert.deepEqual(filterQueue(items).map(i=>i.id),[2,3,1]);assert.deepEqual(filterQueue(items,{tab:'search'}).map(i=>i.id),[1]);assert.deepEqual(items.map(i=>i.id),[1,2,3]);
});
test('offline site, registration and relocation derive exact local tally without duplicate check-ins',()=>{
 const q=[edit('/shelters',{id:'a',max_capacity:10},1),edit('/shelters',{id:'b',max_capacity:10},2),edit('/people',{id:person,full_name:'TEST',status:'in_shelter',shelter_id:'a'},3),edit('/people/'+person+'/check-in',{expected_version:1,status:'in_shelter',shelter_id:'a'},4),edit('/people/'+person+'/check-in',{expected_version:1,status:'relocated',shelter_id:'b'},5)];
 const v=registryView(undefined,q,'Tester');assert.equal(v.counts.registered,1);assert.equal(v.counts.at_sites,1);assert.deepEqual(v.shelters.map(s=>s.current_count),[0,1]);assert.equal(v.people[0].version,2);assert.equal(registryView(undefined,q,'Other').people.length,0);
});
test('stale or rejected saved updates never replace the latest server status',()=>{
 const base={people:[{id:person,status:'needs_medical',version:3,shelter_id:null}],shelters:[]};
 const v=registryView(base,[edit('/people/'+person+'/check-in',{status:'safe',expected_version:1},1)],'Tester');assert.equal(v.people[0].status,'needs_medical');assert.ok(v.people[0].pending_error);
});
test('generated QR is decodable and contains only a valid opaque person ID',()=>{
 const value='RESQ:'+person,m=QRCode.create(value).modules,scale=8,size=(m.size+8)*scale,data=new Uint8ClampedArray(size*size*4).fill(255);
 for(let y=0;y<m.size;y++)for(let x=0;x<m.size;x++)if(m.get(y,x))for(let yy=0;yy<scale;yy++)for(let xx=0;xx<scale;xx++){const i=(((y+4)*scale+yy)*size+(x+4)*scale+xx)*4;data[i]=data[i+1]=data[i+2]=0;}
 assert.equal(jsQR(data,size,size).data,value);assert.equal(parsePersonCode(value),person);assert.equal(parsePersonCode('https://untrusted.example'),null);
});
