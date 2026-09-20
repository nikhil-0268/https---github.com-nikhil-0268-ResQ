import os
from pathlib import Path
from sqlalchemy import create_engine, Column, String, Float, Integer, ForeignKey, JSON, event
from sqlalchemy.orm import declarative_base, sessionmaker

BASE = Path(__file__).parent
DATA = Path(os.getenv('RESQ_DATA_DIR',str(BASE/'data')))
DATA.mkdir(parents=True,exist_ok=True)
engine=create_engine(os.getenv('DATABASE_URL',f'sqlite:///{(DATA/"resq.db").as_posix()}'),connect_args={'check_same_thread':False})
@event.listens_for(engine,'connect')
def foreign_keys(connection, _):
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA busy_timeout=5000')
Session=sessionmaker(bind=engine)
Base=declarative_base()
class Incident(Base):
    __tablename__='incidents'
    id=Column(String,primary_key=True)
    lat=Column(Float); lng=Column(Float); kind=Column(String)
    status=Column(String,default='pending'); status_by=Column(String); status_at=Column(Float)
    previous_incident_id=Column(String,ForeignKey('incidents.id'),nullable=True)
    created_at=Column(Float); last_signal_at=Column(Float)
    manual_priority=Column(Integer,nullable=True); override_at=Column(Float,nullable=True); override_by=Column(String,nullable=True)
class Report(Base):
    __tablename__='reports'
    id=Column(String,primary_key=True)
    incident_id=Column(String,ForeignKey('incidents.id'),nullable=True,index=True)
    payload=Column(JSON,nullable=False)
class Audio(Base):
    __tablename__='audio_events'
    id=Column(String,primary_key=True)
    incident_id=Column(String,ForeignKey('incidents.id'),nullable=False,index=True)
    payload=Column(JSON,nullable=False)
class Environment(Base):
    __tablename__='environmental_events'
    id=Column(String,primary_key=True)
    incident_id=Column(String,ForeignKey('incidents.id'),nullable=True)
    payload=Column(JSON,nullable=False)
class Log(Base):
    __tablename__='incident_events'
    id=Column(String,primary_key=True)
    incident_id=Column(String,ForeignKey('incidents.id'),nullable=True,index=True)
    payload=Column(JSON,nullable=False)
class Alert(Base):
    __tablename__='alerts'
    id=Column(String,primary_key=True)
    incident_id=Column(String,ForeignKey('incidents.id'),nullable=True)
    payload=Column(JSON,nullable=False)
class Mutation(Base):
    __tablename__='mutations'
    id=Column(String,primary_key=True)
    response=Column(JSON,nullable=False)
Base.metadata.create_all(engine)
