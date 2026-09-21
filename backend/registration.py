"""Responder-only people registry. Counts are derived; scans never increment a tally."""
import time,uuid
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import select,func
from .models import Session,Shelter,Person,CheckIn,Mutation

router=APIRouter(prefix='/api',tags=['Registration and check-in'])
Status=Literal['safe','missing','needs_medical','in_shelter','relocated']

def db():
    with Session() as s:
        try:yield s;s.commit()
        except Exception:s.rollback();raise
class Actor(BaseModel):
    actor:str=Field(min_length=2,max_length=80)
    client_id:str=Field(min_length=1,max_length=100)
    @field_validator('actor')
    @classmethod
    def nonempty(cls,v):
        if len(v.strip())<2:raise ValueError('Responder name is required')
        return v.strip()
class ShelterInput(Actor):
    id:str=Field(pattern=r'^S-[A-Fa-f0-9-]{36}$')
    name:str=Field(min_length=2,max_length=120)
    location:str=Field(min_length=2,max_length=200)
    max_capacity:int=Field(ge=1,le=100000,strict=True)
    @field_validator('name','location')
    @classmethod
    def trim(cls,v):
        if len(v.strip())<2:raise ValueError('Name and location must contain text')
        return v.strip()
class PersonInput(Actor):
    id:str=Field(pattern=r'^P-[A-Fa-f0-9-]{36}$')
    full_name:str=Field(min_length=2,max_length=120)
    age:int|None=Field(default=None,ge=0,le=125,strict=True)
    status:Status='safe'
    shelter_id:str|None=None
    note:str=Field(default='',max_length=1000)
    @field_validator('full_name')
    @classmethod
    def trim(cls,v):
        if len(v.strip())<2:raise ValueError('Full name is required')
        return v.strip()
class CheckInInput(Actor):
    status:Status
    shelter_id:str|None=None
    expected_version:int=Field(ge=1,strict=True)
    note:str=Field(default='',max_length=1000)

def person_json(p):return {key:getattr(p,key) for key in ('id','full_name','age','status','shelter_id','created_at','updated_at','version')}
def count(s,sid):return s.scalar(select(func.count()).select_from(Person).where(Person.shelter_id==sid)) or 0

def check_destination(s,status,sid,previous=None):
    if status=='missing' and sid:raise HTTPException(422,'A missing person cannot be counted as present at a site. Clear the site.')
    if status=='in_shelter' and not sid:raise HTTPException(422,'Choose a shelter for In shelter status')
    if sid:
        shelter=s.get(Shelter,sid)
        if not shelter:raise HTTPException(404,'Site not found. Sync the site registration first.')
        if sid!=previous and count(s,sid)>=shelter.max_capacity:raise HTTPException(409,'Site is at capacity. Choose another site or leave the person unassigned.')

def previous_response(s,b,operation):
    record=s.get(Mutation,'registry:'+b.client_id)
    if record:
        if record.response.get('_operation')!=operation:raise HTTPException(409,'This request ID was already used for another operation')
        return {k:v for k,v in record.response.items() if k!='_operation'}
def save_response(s,b,operation,response):
    s.add(Mutation(id='registry:'+b.client_id,response={**response,'_operation':operation}));return response

def record_event(s,p,b,old_site=None):
    s.add(CheckIn(id='c-'+uuid.uuid4().hex,person_id=p.id,shelter_id=p.shelter_id,previous_shelter_id=old_site,status=p.status,actor=b.actor,note=b.note,created_at=time.time()))

@router.get('/registry')
def registry(s=Depends(db,scope='function')):
    # Read a coherent snapshot of people and sites. Derive counts from these same records.
    people=[person_json(p) for p in s.scalars(select(Person).order_by(Person.updated_at.desc()))]
    sites=[]
    for site in s.scalars(select(Shelter).order_by(Shelter.name)):
        current=sum(p['shelter_id']==site.id for p in people)
        sites.append(dict(id=site.id,name=site.name,location=site.location,max_capacity=site.max_capacity,current_count=current,available=max(0,site.max_capacity-current),created_at=site.created_at))
    return dict(people=people,shelters=sites,as_of=time.time(),counts=dict(registered=len(people),at_sites=sum(bool(p['shelter_id']) for p in people),needs_medical=sum(p['status']=='needs_medical' for p in people),missing=sum(p['status']=='missing' for p in people)))

@router.post('/shelters')
def add_shelter(b:ShelterInput,s=Depends(db,scope='function')):
    operation='shelter:'+b.id
    if old:=previous_response(s,b,operation):return old
    if s.get(Shelter,b.id):raise HTTPException(409,'This site ID already exists')
    site=Shelter(id=b.id,name=b.name,location=b.location,max_capacity=b.max_capacity,created_at=time.time());s.add(site);s.flush()
    return save_response(s,b,operation,dict(id=site.id,name=site.name,location=site.location,max_capacity=site.max_capacity,current_count=0,created_at=site.created_at))

@router.post('/people')
def add_person(b:PersonInput,s=Depends(db,scope='function')):
    operation='person:'+b.id
    if old:=previous_response(s,b,operation):return old
    if s.get(Person,b.id):raise HTTPException(409,'This person ID already exists. Open the existing profile.')
    check_destination(s,b.status,b.shelter_id)
    now=time.time();p=Person(id=b.id,full_name=b.full_name,age=b.age,status=b.status,shelter_id=b.shelter_id,created_at=now,updated_at=now,version=1);s.add(p);s.flush();record_event(s,p,b)
    return save_response(s,b,operation,person_json(p))

@router.patch('/people/{pid}/check-in')
def check_in(pid:str,b:CheckInInput,s=Depends(db,scope='function')):
    operation='check-in:'+pid
    if old:=previous_response(s,b,operation):return old
    p=s.get(Person,pid)
    if not p:raise HTTPException(404,'Person not found. Sync the registration first.')
    if p.version!=b.expected_version:raise HTTPException(409,'This profile changed on another device. Review the latest status before applying your saved change.')
    check_destination(s,b.status,b.shelter_id,p.shelter_id)
    old_site=p.shelter_id
    if p.status!=b.status or p.shelter_id!=b.shelter_id or b.note.strip():
        p.status=b.status;p.shelter_id=b.shelter_id;p.updated_at=time.time();p.version+=1;record_event(s,p,b,old_site)
    return save_response(s,b,operation,person_json(p))

@router.get('/people/{pid}/history')
def history(pid:str,s=Depends(db,scope='function')):
    if not s.get(Person,pid):raise HTTPException(404,'Person not found')
    return [{k:getattr(e,k) for k in ('id','person_id','shelter_id','previous_shelter_id','status','actor','note','created_at')} for e in s.scalars(select(CheckIn).where(CheckIn.person_id==pid).order_by(CheckIn.created_at.desc()))]
