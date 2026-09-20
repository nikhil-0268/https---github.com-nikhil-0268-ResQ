import os, json, time, uuid, secrets, threading, io, wave, math, struct, asyncio
from pathlib import Path
from collections import defaultdict, deque
from typing import Literal
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent/'.env')
from fastapi import FastAPI, Depends, Header, HTTPException, Form, File, UploadFile, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from .models import Session, Incident, Report, Audio, Environment, Log, Alert, Mutation, DATA
from .scoring import distance, risk, calculate, rank, OPEN, SEARCH
from .extraction import extract

app=FastAPI(title='ResQ',version='1.0.0')
CODE=os.getenv('RESPONDER_CODE','resq-demo')
AREAS=json.loads((Path(__file__).parent/'gazetteer.json').read_text(encoding='utf-8-sig'))
LOCK=threading.RLock()
RATE=defaultdict(deque)
WRITE_LOCK=asyncio.Lock()
@app.middleware('http')
async def serialize_mutations(request, call_next):
    if request.method in ('POST','PATCH','DELETE','PUT'):
        async with WRITE_LOCK:
            return await call_next(request)
    return await call_next(request)


def uid(prefix): return prefix+'-'+uuid.uuid4().hex[:10]
def auth(x_responder_code: str=Header(default='')):
    if not secrets.compare_digest(x_responder_code,CODE): raise HTTPException(401,'Responder code required')
def db():
    with Session() as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback(); raise

def rows(s, model, iid=None):
    query=select(model)
    if iid is not None: query=query.where(model.incident_id==iid)
    return [dict(x.payload,id=x.id,incident_id=x.incident_id) for x in s.scalars(query)]
def log(s,iid,kind,text,actor='system'):
    s.add(Log(id=uid('log'),incident_id=iid,payload=dict(kind=kind,text=text,actor=actor,created_at=time.time())))
def alert(s,iid,kind,text,ne,sim=False):
    s.add(Alert(id=uid('alert'),incident_id=iid,payload=dict(kind=kind,text=text,ne=ne,is_simulated=sim,created_at=time.time())))
def get(s,model,id):
    item=s.get(model,id)
    if not item: raise HTTPException(404,'Not found')
    return item

def location(lat,lng,area=None):
    if lat is not None or lng is not None:
        if lat is None or lng is None or not math.isfinite(lat) or not math.isfinite(lng) or not -90<=lat<=90 or not -180<=lng<=180: raise HTTPException(422,'Valid latitude and longitude required')
        return lat,lng
    found=next((a for a in AREAS if a['name']==area),None)
    return (found['lat'],found['lng']) if found else (None,None)
def place(lat,lng):
    a=min(AREAS,key=lambda a:distance((lat,lng),(a['lat'],a['lng'])))
    return a['name']+' · '+a['ne'] if distance((lat,lng),(a['lat'],a['lng']))<1500 else f'{lat:.4f}, {lng:.4f}'
def group(s,lat,lng,kind,audio=False):
    if lat is None: return None
    now=time.time(); candidates=[]; previous=None
    for i in s.scalars(select(Incident)):
        d=distance((lat,lng),(i.lat,i.lng))
        if d>100: continue
        if i.status not in OPEN: previous=i.id; continue
        compatible=audio or i.kind==kind or (i.kind in SEARCH and kind in SEARCH)
        if compatible and (audio or now-i.last_signal_at<=10800): candidates.append((d,i))
    if candidates: return min(candidates,key=lambda x:x[0])[1]
    i=Incident(id=uid('i'),lat=lat,lng=lng,kind=kind,status='pending',status_by='system',status_at=now,created_at=now,last_signal_at=now,previous_incident_id=previous)
    s.add(i); s.flush(); log(s,i.id,'incident_created','Incident opened for human review.')
    return i

def centroid(s,i):
    s.flush()
    signals=rows(s,Report,i.id)+rows(s,Audio,i.id)
    points=[r for r in signals if r.get('lat') is not None]
    if points:
        i.lat=sum(p['lat'] for p in points)/len(points); i.lng=sum(p['lng'] for p in points)/len(points)
    i.last_signal_at=time.time()
def context(s,i):
    signals=[e for e in rows(s,Environment) if distance((i.lat,i.lng),(e['lat'],e['lng']))<=10000 and 0<=time.time()-e['observed_at']<=10800]
    result=dict(temperature=None,temperature_risk=None,rainfall_mm_per_hour=None,landslide_risk=None)
    for e in sorted(signals,key=lambda e:e['observed_at']):
        if e['event_type']=='temperature': result.update(temperature=e['value'],temperature_risk=e['risk_level'])
        if e['event_type']=='rainfall': result['rainfall_mm_per_hour']=e['value']
        if e['event_type']=='landslide_assessment': result['landslide_risk']=e['risk_level']
    result['is_simulated']=any(e['is_simulated'] for e in signals)
    return result,signals

def serialize(s,i,detail=False):
    rs,aus=rows(s,Report,i.id),rows(s,Audio,i.id)
    env,es=context(s,i)
    result=dict(id=i.id,lat=i.lat,lng=i.lng,place_name=place(i.lat,i.lng),primary_type=i.kind,status=i.status,status_by=i.status_by,status_at=i.status_at,created_at=i.created_at,last_signal_at=i.last_signal_at,manual_priority=i.manual_priority,override_at=i.override_at,override_by=i.override_by,previous_incident_id=i.previous_incident_id,environmental_context=env,is_simulated=any(r['is_simulated'] for r in rs+aus+es),**calculate(rs,aus,env))
    result['has_hazard']=env['landslide_risk']=='high' or (env['temperature'] is not None and env['temperature']<0) or (env['rainfall_mm_per_hour'] or 0)>10
    if detail:
        for a in aus: a.pop('file_path',None)
        for r in rs: r.pop('photo_path',None)
        result.update(reports=rs,audio_events=aus,environmental_events=es,log=sorted(rows(s,Log,i.id),key=lambda x:-x['created_at']),alerts=sorted(rows(s,Alert,i.id),key=lambda x:-x['created_at'])[:10])
    return result

def emit_incident(s,i,kind='report'):
    s.flush(); d=serialize(s,i)
    if d['priority'] in ('high','medium'):
        alert(s,i.id,kind,f"{d['priority'].upper()} · {d['place_name']}. Review evidence.",f"{ 'उच्च' if d['priority']=='high' else 'मध्यम'} प्राथमिकता · {d['place_name']}। विवरण जाँच गर्नुहोस्।",d['is_simulated'])
    if d['environmental_context']['landslide_risk']=='high': alert(s,i.id,'landslide','Report in a high landslide risk zone. Assess slope safety.','उच्च पहिरो जोखिम क्षेत्रमा रिपोर्ट। ढलानको सुरक्षा जाँच गर्नुहोस्।',d['is_simulated'])

class Login(BaseModel):
    code: str
@app.post('/api/auth/check')
def login(body:Login):
    if not secrets.compare_digest(body.code,CODE): raise HTTPException(401,'Incorrect responder code')
    return {'ok':True,'demo_code':CODE=='resq-demo'}
@app.get('/api/config')
def config(): return dict(emergency_numbers=os.getenv('EMERGENCY_NUMBERS_TEXT','Nepal Police: 100 · Ambulance Nepal: 102. Published official contacts checked 20 September 2026; local availability may vary.'),extraction='claude' if os.getenv('ANTHROPIC_API_KEY') else 'rules_fallback',audio_mode='manual_review',weather='manual input',demo_code=CODE=='resq-demo')
@app.get('/api/gazetteer')
def gazetteer(): return AREAS
@app.get('/api/health')
def health(): return {'ok':True}

@app.post('/api/reports')
def report(request:Request,message:str=Form(min_length=3,max_length=5000),lat:float|None=Form(None),lng:float|None=Form(None),area:str|None=Form(None),location_source:Literal['gps','pin','gazetteer','none']=Form('pin'),phone:str=Form('',max_length=40),client_id:str=Form(default='',max_length=100),photo:UploadFile|None=File(None),s=Depends(db, scope='function')):
    if client_id and (old:=s.get(Mutation,'report:'+client_id)): return old.response
    now=time.time(); key=request.client.host if request.client else 'local'; q=RATE[key]
    while q and q[0]<now-60: q.popleft()
    if len(q)>=10: raise HTTPException(429,'Too many reports. Retry after one minute.')
    q.append(now)
    lat,lng=location(lat,lng,area)
    rid=uid('r'); photo_path=None
    if photo:
        raw=photo.file.read(5*1024*1024+1)
        if len(raw)>5*1024*1024: raise HTTPException(413,'Photo must be at most 5 MB')
        ext='.jpg' if raw.startswith(b'\xff\xd8\xff') else '.png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else None
        if not ext: raise HTTPException(422,'Upload a JPEG or PNG photo')
        photo_path=str(DATA/(rid+ext)); Path(photo_path).write_bytes(raw)
    # Persist original BEFORE external extraction, including on model failure.
    r=Report(id=rid,payload=dict(original_message=message,contact_phone=phone or None,photo_path=photo_path,has_photo=bool(photo_path),created_at=now,is_simulated=False,verification_status='unreviewed',extraction_status='failed',lat=lat,lng=lng,incident_type='unknown'))
    s.add(r); s.commit()
    data,status,method,error=extract(message)
    if lat is None:
        found=next((a for a in AREAS if a['name'].lower() in (data.get('place_name') or '').lower() or a['ne'] in (data.get('place_name') or '')),None)
        if found: lat,lng=found['lat'],found['lng']; location_source='gazetteer'
    i=group(s,lat,lng,data['incident_type'])
    r.incident_id=i.id if i else None
    r.payload={**r.payload,**data,'lat':lat,'lng':lng,'location_source':location_source if lat is not None else 'none','extraction_status':status,'extraction_method':method,'extraction_error':error}
    log(s,r.incident_id,'report_received',error or 'Report received and extracted.')
    if i: centroid(s,i); emit_incident(s,i)
    response={'id':rid,'received':True,'message':'Report received. A responder will review it.'}
    if client_id: s.add(Mutation(id='report:'+client_id,response=response))
    return response

@app.get('/api/incidents',dependencies=[Depends(auth)])
def incidents(s=Depends(db, scope='function')): return rank([serialize(s,i) for i in s.scalars(select(Incident))])
@app.get('/api/incidents/{iid}',dependencies=[Depends(auth)])
def detail(iid:str,s=Depends(db, scope='function')):
    d=serialize(s,get(s,Incident,iid),True)
    ranked=incidents(s)
    d['rescue_priority']=next(x['rescue_priority'] for x in ranked if x['id']==iid)
    return d
@app.get('/api/reports/unlocated',dependencies=[Depends(auth)])
def unlocated(s=Depends(db, scope='function')): return [r for r in rows(s,Report) if r['incident_id'] is None]

class Action(BaseModel):
    actor:str=Field(min_length=2,max_length=80,pattern=r'.*\S.*')
    note:str=Field(default='',max_length=2000)
    client_id:str=Field(default='',max_length=100)
class Status(Action):
    status:Literal['pending','investigating','activity_confirmed','resolved','false_alarm']
class Priority(Action):
    priority:int|None=Field(default=None,ge=1,le=10000)
class Verify(Action):
    status:Literal['verified','rejected','needs_info']
    reason:str=Field(default='',max_length=400)
class Review(Action):
    status:Literal['confirmed_human','false_alarm','unknown']
class Locate(Action):
    lat:float=Field(ge=-90,le=90); lng:float=Field(ge=-180,le=180)

def duplicate(s,b): return s.get(Mutation,'action:'+b.client_id) if b.client_id else None
def done(s,b):
    result={'ok':True}
    if b.client_id: s.add(Mutation(id='action:'+b.client_id,response=result))
    return result
@app.patch('/api/incidents/{iid}/status',dependencies=[Depends(auth)])
def status(iid:str,b:Status,s=Depends(db, scope='function')):
    if old:=duplicate(s,b): return old.response
    i=get(s,Incident,iid)
    allowed={'pending':['investigating'],'investigating':['activity_confirmed','false_alarm','resolved'],'activity_confirmed':['resolved'],'resolved':['pending'],'false_alarm':['pending']}
    if b.status not in allowed[i.status]: raise HTTPException(409,f'Cannot move {i.status} to {b.status}; refresh and review.')
    i.status=b.status; i.status_by=b.actor.strip(); i.status_at=time.time()
    log(s,iid,'status_change',b.status.replace('_',' ')+' · '+b.note,b.actor)
    alert(s,iid,'status',f'{place(i.lat,i.lng)} · {b.status.replace("_"," ")} by {b.actor}',f'{place(i.lat,i.lng)} · स्थिति परिवर्तन: {b.actor}',serialize(s,i)['is_simulated'])
    return done(s,b)
@app.patch('/api/incidents/{iid}/rescue_priority',dependencies=[Depends(auth)])
def priority(iid:str,b:Priority,s=Depends(db, scope='function')):
    if old:=duplicate(s,b): return old.response
    i=get(s,Incident,iid)
    if b.priority and (i.status not in OPEN or not serialize(s,i)['is_search_relevant']): raise HTTPException(409,'Only open search incidents can be ranked')
    if b.priority and not b.note.strip(): raise HTTPException(422,'Give a reason for the priority override')
    i.manual_priority=b.priority; i.override_by=b.actor; i.override_at=time.time()
    log(s,iid,'rescue_priority_set',f'Priority {b.priority or "automatic"}. {b.note}',b.actor)
    return done(s,b)
@app.post('/api/incidents/{iid}/note',dependencies=[Depends(auth)])
def note(iid:str,b:Action,s=Depends(db, scope='function')):
    if old:=duplicate(s,b): return old.response
    get(s,Incident,iid)
    if not b.note.strip(): raise HTTPException(422,'Note is required')
    log(s,iid,'note',b.note,b.actor); return done(s,b)
@app.patch('/api/reports/{rid}/verification',dependencies=[Depends(auth)])
def verify(rid:str,b:Verify,s=Depends(db, scope='function')):
    if old:=duplicate(s,b): return old.response
    r=get(s,Report,rid)
    if b.status=='rejected' and not b.reason.strip(): raise HTTPException(422,'Rejection reason is required')
    r.payload={**r.payload,'verification_status':b.status,'verification_reason':b.reason,'verification_note':b.note,'reviewed_by':b.actor,'reviewed_at':time.time()}
    log(s,r.incident_id,'verification',f'Report {rid}: {b.status}. {b.reason} {b.note}',b.actor)
    return done(s,b)
@app.patch('/api/reports/{rid}/location',dependencies=[Depends(auth)])
def locate(rid:str,b:Locate,s=Depends(db, scope='function')):
    if old:=duplicate(s,b): return old.response
    r=get(s,Report,rid)
    if r.incident_id: raise HTTPException(409,'This report already has a location')
    i=group(s,b.lat,b.lng,r.payload['incident_type']); r.incident_id=i.id
    r.payload={**r.payload,'lat':b.lat,'lng':b.lng,'location_source':'responder'}
    log(s,i.id,'report_attached','Responder supplied a location. '+b.note,b.actor); centroid(s,i); emit_incident(s,i)
    return done(s,b)
@app.get('/api/reports/{rid}/photo',dependencies=[Depends(auth)])
def photo(rid:str,s=Depends(db, scope='function')):
    path=get(s,Report,rid).payload.get('photo_path')
    if not path or not Path(path).exists(): raise HTTPException(404,'Photo unavailable')
    return FileResponse(path)

DEMO={'tapping':('TAPPING_KNOCKING',True,True,4),'voice':('VOICE',True,False,None),'cough':('COUGHING',True,False,None),'traffic':('NON_HUMAN',False,False,None),'silence':('NON_HUMAN',False,False,None)}
@app.post('/api/audio',dependencies=[Depends(auth)])
def audio(lat:float=Form(...),lng:float=Form(...),actor:str=Form(min_length=2,max_length=80),note:str=Form('',max_length=2000),demo:str=Form(''),location_source:Literal['gps','pin','gazetteer']=Form('pin'),file:UploadFile|None=File(None),client_id:str=Form('',max_length=100),s=Depends(db, scope='function')):
    if client_id and (old:=s.get(Mutation,'audio:'+client_id)): return old.response
    lat,lng=location(lat,lng); aid=uid('a'); path=None; duration=None
    label,human,repeated,count='UNKNOWN',None,None,None
    if demo:
        if demo not in DEMO or file: raise HTTPException(422,'Choose one demo sample or one real file')
        label,human,repeated,count=DEMO[demo]
        # Audible synthetic tapping fixture, never represented as a recorded detection.
        if demo in ('tapping','silence'):
            path=str(DATA/(aid+'.wav')); duration=3
            with wave.open(path,'wb') as w:
                w.setparams((1,2,16000,0,'NONE','not compressed'))
                samples=[]
                for k in range(48000):
                    t=k/16000; x=0
                    if demo=='tapping':
                        for onset in (.4,1,1.6,2.2):
                            d=t-onset
                            if 0<=d<.06: x+=math.sin(d*2*math.pi*800)*math.exp(-d*65)*14000
                    samples.append(struct.pack('<h',int(x)))
                w.writeframes(b''.join(samples))
    elif file:
        raw=file.file.read(10*1024*1024+1)
        if len(raw)>10*1024*1024: raise HTTPException(413,'Audio must be at most 10 MB')
        ext=Path(file.filename or '').suffix.lower()
        if ext not in ('.wav','.mp3','.m4a'): raise HTTPException(422,'Use WAV, MP3 or M4A')
        try:
            if ext=='.wav':
                with wave.open(io.BytesIO(raw)) as w: duration=w.getnframes()/w.getframerate()
            else:
                import mutagen
                parsed=mutagen.File(io.BytesIO(raw))
                duration=parsed.info.length
            if not duration or not math.isfinite(duration) or duration>30: raise ValueError()
        except Exception: raise HTTPException(422,'Audio is invalid or exceeds 30 seconds')
        path=str(DATA/(aid+ext)); Path(path).write_bytes(raw)
    else: raise HTTPException(422,'Choose audio or an explicitly simulated sample')
    i=group(s,lat,lng,'audio',True)
    payload=dict(label=label,human_type=human,repeated_signal=repeated,onset_count=count,lat=lat,lng=lng,location_source=location_source,recorded_by=actor,note=note,file_path=path,has_file=bool(path),original_filename=file.filename if file else f'Simulated {demo}',duration_s=duration,mode='demo_label' if demo else 'unavailable',review_status='unreviewed',is_simulated=bool(demo),created_at=time.time())
    s.add(Audio(id=aid,incident_id=i.id,payload=payload)); centroid(s,i)
    log(s,i.id,'audio_received','SIMULATED label: '+label if demo else 'Audio stored. Model unavailable; human review required.',actor)
    alert(s,i.id,'audio',('SIMULATED · ' if demo else '')+'Audio signal submitted at '+place(lat,lng),('नमुना · ' if demo else '')+'ध्वनि संकेत प्राप्त: '+place(lat,lng),bool(demo))
    response={**payload,'file_path':None,'id':aid,'incident_id':i.id}
    if client_id: s.add(Mutation(id='audio:'+client_id,response=response))
    return response
@app.get('/api/audio/{aid}/file',dependencies=[Depends(auth)])
def audio_file(aid:str,s=Depends(db, scope='function')):
    path=get(s,Audio,aid).payload.get('file_path')
    if not path or not Path(path).exists(): raise HTTPException(404,'This demo label has no recording')
    return FileResponse(path)
@app.patch('/api/audio/{aid}/review',dependencies=[Depends(auth)])
def review(aid:str,b:Review,s=Depends(db, scope='function')):
    if old:=duplicate(s,b): return old.response
    a=get(s,Audio,aid); a.payload={**a.payload,'review_status':b.status,'review_note':b.note,'reviewed_by':b.actor,'reviewed_at':time.time()}
    log(s,a.incident_id,'verification',f'Audio {aid}: {b.status}. {b.note}',b.actor)
    return done(s,b)

class Sensor(Action):
    event_type:Literal['temperature','rainfall','landslide_assessment']
    value:float=Field(allow_inf_nan=False)
    lat:float=Field(ge=-90,le=90); lng:float=Field(ge=-180,le=180)
    observed_at:float|None=None
    location_source:Literal['gps','pin','gazetteer','api']='pin'

def add_sensor(s,b,sim=False):
    if b.event_type=='temperature' and not -100<=b.value<=70: raise HTTPException(422,'Temperature must be -100 to 70°C')
    if b.event_type=='rainfall' and not 0<=b.value<=1000: raise HTTPException(422,'Rainfall must be 0 to 1000 mm/h')
    if b.event_type=='landslide_assessment' and b.value not in (1,2,3): raise HTTPException(422,'Risk must be 1, 2 or 3')
    observed=b.observed_at if b.observed_at is not None else time.time()
    if not math.isfinite(observed) or observed>time.time()+300 or observed<0: raise HTTPException(422,'Timestamp must be valid and not in the future')
    candidates=[(distance((b.lat,b.lng),(i.lat,i.lng)),i) for i in s.scalars(select(Incident)) if i.status in OPEN]
    nearest=min(candidates,key=lambda x:x[0]) if candidates else None
    iid=nearest[1].id if nearest and nearest[0]<=10000 else None
    level=risk(b.event_type,b.value)
    payload=dict(event_type=b.event_type,value=b.value,lat=b.lat,lng=b.lng,risk_level=level,observed_at=observed,created_at=time.time(),source='manual',recorded_by=b.actor,location_source=b.location_source,is_simulated=sim,note=b.note)
    e=Environment(id=uid('env'),incident_id=iid,payload=payload); s.add(e)
    if time.time()-observed<=10800 and (level=='critical' or b.event_type=='landslide_assessment' and level=='high'):
        text=f'{b.event_type.replace("_"," ").upper()} · {b.value} · {place(b.lat,b.lng)}. Check access and field conditions.'
        ne=f'{ {"temperature":"तापक्रम", "rainfall":"वर्षा", "landslide_assessment":"पहिरो जोखिम"}[b.event_type]} · {b.value} · {place(b.lat,b.lng)}। क्षेत्रको अवस्था जाँच गर्नुहोस्।'
        alert(s,iid,'environment',text,ne,sim); log(s,iid,'environmental_alert',text,b.actor)
    return dict(id=e.id,incident_id=iid,**payload)
@app.post('/api/sensors',dependencies=[Depends(auth)])
def sensor(b:Sensor,s=Depends(db, scope='function')):
    if old:=duplicate(s,b): return old.response
    response=add_sensor(s,b)
    if b.client_id: s.add(Mutation(id='action:'+b.client_id,response=response))
    return response
@app.get('/api/environmental',dependencies=[Depends(auth)])
def environmental(s=Depends(db, scope='function')): return sorted(rows(s,Environment),key=lambda x:-x['observed_at'])
@app.get('/api/heat',dependencies=[Depends(auth)])
def heat(s=Depends(db, scope='function')):
    return [[r['lat'],r['lng'],{'high':1,'medium':.6,'low':.3}.get(r.get('severity'),.3)] for r in rows(s,Report) if r['lat'] is not None and r['verification_status']!='rejected']
@app.get('/api/alerts',dependencies=[Depends(auth)])
def alerts(after:float=0,s=Depends(db, scope='function')):
    return sorted([a for a in rows(s,Alert) if a['created_at']>after],key=lambda x:-x['created_at'])[:100]

@app.post('/api/demo/seed',dependencies=[Depends(auth)])
def seed(s=Depends(db, scope='function')):
    if any(r['is_simulated'] for r in rows(s,Report)): return {'ok':True,'already_seeded':True}
    groups=[(0,'building_collapse',5),(1,'trapped_people',4),(2,'building_collapse',3),(3,'road_blocked',3),(4,'medical_need',2),(6,'landslide',3)]
    for index,kind,count in groups:
        area=AREAS[index]
        for n in range(count):
            lat,lng=area['lat']+n*.000035,area['lng']+n*.00002
            i=group(s,lat,lng,kind)
            messages=[f"{area['name']} ma building bhatkeko, manche bhitra faseko.",f"{area['ne']}मा घर भत्किएको छ, भित्र मान्छेहरू फसेका छन्।",f"Reported {kind.replace('_',' ')} near {area['name']}. Please investigate."] if kind in SEARCH else [f"Reported {kind.replace('_',' ')} near {area['name']}."]
            message=messages[n%len(messages)]
            data,_,_,_=extract_demo(message,kind)
            r=Report(id=uid('r'),incident_id=i.id,payload=dict(**data,original_message=message,lat=lat,lng=lng,location_source='gazetteer',contact_phone=None,photo_path=None,has_photo=False,created_at=time.time()-n*120,verification_status='unreviewed',is_simulated=True,extraction_status='ok',extraction_method='demo_fixture',extraction_error=None))
            s.add(r); centroid(s,i); log(s,i.id,'report_received','SIMULATED citizen report received.')
        if index in (0,1):
            s.add(Audio(id=uid('a'),incident_id=i.id,payload=dict(label='TAPPING_KNOCKING' if index==0 else 'VOICE',human_type=True,repeated_signal=index==0,onset_count=4 if index==0 else None,lat=area['lat'],lng=area['lng'],recorded_by='Demo responder',mode='demo_label',review_status='unreviewed',is_simulated=True,created_at=time.time(),has_file=False,file_path=None,duration_s=None,note='SIMULATED label fixture; no model inference.')))
        emit_incident(s,i)
    for index,kind,value in [(0,'temperature',-2),(1,'rainfall',12),(6,'landslide_assessment',3)]:
        a=AREAS[index]; add_sensor(s,Sensor(actor='Demo sensor',event_type=kind,value=value,lat=a['lat'],lng=a['lng']),True)
    return {'ok':True,'reports':20}
def extract_demo(message,kind):
    from .extraction import fallback
    d=fallback(message); d['incident_type']=kind
    return d,'ok','demo_fixture',None
@app.post('/api/demo/reset',dependencies=[Depends(auth)])
def reset(s=Depends(db, scope='function')):
    for model in (Report,Audio,Environment):
        for item in list(s.scalars(select(model))):
            if item.payload.get('is_simulated'):
                for field in ('file_path','photo_path'):
                    if item.payload.get(field): Path(item.payload[field]).unlink(missing_ok=True)
                s.delete(item)
    s.flush()
    for a in list(s.scalars(select(Alert))):
        if a.payload.get('is_simulated'): s.delete(a)
    s.flush()
    for i in list(s.scalars(select(Incident))):
        if not rows(s,Report,i.id) and not rows(s,Audio,i.id):
            for model in (Log,Alert):
                for item in list(s.scalars(select(model).where(model.incident_id==i.id))): s.delete(item)
            for e in s.scalars(select(Environment).where(Environment.incident_id==i.id)): e.incident_id=None
            for other in s.scalars(select(Incident).where(Incident.previous_incident_id==i.id)): other.previous_incident_id=None
            s.flush(); s.delete(i)
        else: centroid(s,i)
    return {'ok':True}
