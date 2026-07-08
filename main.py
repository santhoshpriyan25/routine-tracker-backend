from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, func, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from fastapi.middleware.cors import CORSMiddleware

engine = create_engine("sqlite:///./routine.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

VALID_CATEGORIES = ["Study","Food","Sleep","Exercise","Work","Personal","Health","Other"]
VALID_REPEATS    = ["none", "daily", "weekdays", "weekly"]

class Pin(Base):
    __tablename__ = "pins"
    id             = Column(Integer, primary_key=True, index=True)
    note           = Column(String, nullable=False)
    category       = Column(String, default="Other")
    scheduled_time = Column(DateTime, default=datetime.utcnow)
    completed      = Column(Boolean, default=False)
    created_at     = Column(DateTime, default=datetime.utcnow)
    repeat         = Column(String, default="none")
    is_template    = Column(Boolean, default=False)
    template_id    = Column(Integer, nullable=True)

Base.metadata.create_all(bind=engine)

def migrate():
    with engine.connect() as conn:
        existing = [row[1] for row in conn.execute(text("PRAGMA table_info(pins)"))]
        if "repeat" not in existing:
            conn.execute(text("ALTER TABLE pins ADD COLUMN repeat TEXT DEFAULT 'none'"))
            conn.commit()
        if "is_template" not in existing:
            conn.execute(text("ALTER TABLE pins ADD COLUMN is_template INTEGER DEFAULT 0"))
            conn.commit()
        if "template_id" not in existing:
            conn.execute(text("ALTER TABLE pins ADD COLUMN template_id INTEGER"))
            conn.commit()

migrate()

app = FastAPI(title="Routine Tracker API", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class PinCreate(BaseModel):
    note:           str
    category:       str = "Other"
    scheduled_time: datetime
    repeat:         str = "none"

class PinUpdate(BaseModel):
    note:           Optional[str]      = None
    category:       Optional[str]      = None
    scheduled_time: Optional[datetime] = None
    completed:      Optional[bool]     = None
    repeat:         Optional[str]      = None

class PinOut(BaseModel):
    id:             int
    note:           str
    category:       str
    scheduled_time: datetime
    completed:      bool
    created_at:     datetime
    repeat:         str
    is_template:    bool
    template_id:    Optional[int]
    class Config:
        from_attributes = True

def should_repeat_today(repeat: str, ref_time: datetime, today: datetime) -> bool:
    if repeat == "daily":    return True
    if repeat == "weekdays": return today.weekday() < 5
    if repeat == "weekly":   return today.weekday() == ref_time.weekday()
    return False

@app.get("/")
def root(): return {"message": "Routine Tracker API v3 🚀"}

@app.post("/pins/", response_model=PinOut)
def create_pin(pin: PinCreate):
    if pin.category not in VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category")
    if pin.repeat not in VALID_REPEATS:
        raise HTTPException(400, f"Invalid repeat")
    db = SessionLocal()
    is_template = pin.repeat != "none"
    new_pin = Pin(note=pin.note, category=pin.category,
                  scheduled_time=pin.scheduled_time, repeat=pin.repeat,
                  is_template=is_template, created_at=datetime.utcnow())
    db.add(new_pin)
    db.commit()
    db.refresh(new_pin)
    if is_template:
        today = datetime.utcnow()
        if should_repeat_today(pin.repeat, pin.scheduled_time, today):
            inst_time = new_pin.scheduled_time.replace(year=today.year, month=today.month, day=today.day)
            db.add(Pin(note=new_pin.note, category=new_pin.category,
                       scheduled_time=inst_time, repeat="none",
                       is_template=False, template_id=new_pin.id,
                       created_at=datetime.utcnow()))
            db.commit()
    db.close()
    return new_pin

@app.get("/pins/", response_model=list[PinOut])
def get_pins(filter_date: Optional[str]=None, category: Optional[str]=None,
             completed: Optional[bool]=None, include_templates: bool=False):
    db = SessionLocal()
    query = db.query(Pin)
    if not include_templates:
        query = query.filter(Pin.is_template == False)
    if filter_date:  query = query.filter(Pin.scheduled_time.like(f"{filter_date}%"))
    if category:     query = query.filter(Pin.category == category)
    if completed is not None: query = query.filter(Pin.completed == completed)
    pins = query.order_by(Pin.scheduled_time.asc()).all()
    db.close()
    return pins

@app.get("/pins/templates/", response_model=list[PinOut])
def get_templates():
    db = SessionLocal()
    pins = db.query(Pin).filter(Pin.is_template == True).all()
    db.close()
    return pins

@app.post("/pins/generate-recurring/")
def generate_recurring(target_date: Optional[str]=None):
    db = SessionLocal()
    today = datetime.utcnow()
    if target_date:
        today = datetime.fromisoformat(target_date)
    today_str = today.strftime("%Y-%m-%d")
    templates = db.query(Pin).filter(Pin.is_template == True).all()
    created = 0
    for tmpl in templates:
        if not should_repeat_today(tmpl.repeat, tmpl.scheduled_time, today): continue
        existing = db.query(Pin).filter(Pin.template_id == tmpl.id,
                                        Pin.scheduled_time.like(f"{today_str}%")).first()
        if existing: continue
        inst_time = tmpl.scheduled_time.replace(year=today.year, month=today.month, day=today.day)
        db.add(Pin(note=tmpl.note, category=tmpl.category,
                   scheduled_time=inst_time, repeat="none",
                   is_template=False, template_id=tmpl.id,
                   created_at=datetime.utcnow()))
        created += 1
    db.commit()
    db.close()
    return {"status": "ok", "instances_created": created, "date": today_str}

@app.get("/pins/{pin_id}", response_model=PinOut)
def get_pin(pin_id: int):
    db = SessionLocal()
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    db.close()
    if not pin: raise HTTPException(404, "Pin not found")
    return pin

@app.put("/pins/{pin_id}", response_model=PinOut)
def update_pin(pin_id: int, updates: PinUpdate):
    db = SessionLocal()
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    if not pin: db.close(); raise HTTPException(404, "Pin not found")
    if updates.note is not None:           pin.note = updates.note
    if updates.category is not None:       pin.category = updates.category
    if updates.scheduled_time is not None: pin.scheduled_time = updates.scheduled_time
    if updates.completed is not None:      pin.completed = updates.completed
    if updates.repeat is not None:
        pin.repeat = updates.repeat
        pin.is_template = updates.repeat != "none"
    db.commit(); db.refresh(pin); db.close()
    return pin

@app.patch("/pins/{pin_id}/complete", response_model=PinOut)
def toggle_complete(pin_id: int):
    db = SessionLocal()
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    if not pin: db.close(); raise HTTPException(404, "Pin not found")
    pin.completed = not pin.completed
    db.commit(); db.refresh(pin); db.close()
    return pin

@app.delete("/pins/{pin_id}")
def delete_pin(pin_id: int, delete_all_instances: bool=False):
    db = SessionLocal()
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    if not pin: db.close(); raise HTTPException(404, "Pin not found")
    if delete_all_instances and pin.is_template:
        db.query(Pin).filter(Pin.template_id == pin_id).delete()
    db.delete(pin); db.commit(); db.close()
    return {"status": "success", "deleted_id": pin_id}

@app.get("/stats/")
def get_stats(filter_date: Optional[str]=None):
    db = SessionLocal()
    query = db.query(Pin).filter(Pin.is_template == False)
    if filter_date: query = query.filter(Pin.scheduled_time.like(f"{filter_date}%"))
    total = query.count()
    completed = query.filter(Pin.completed == True).count()
    cat_rows = (db.query(Pin.category, func.count(Pin.id))
                .filter(Pin.is_template == False)
                .filter(Pin.scheduled_time.like(f"{filter_date}%") if filter_date else True)
                .group_by(Pin.category).all())
    db.close()
    return {"total": total, "completed": completed, "pending": total - completed,
            "completion_pct": round((completed / total * 100) if total else 0, 1),
            "by_category": {cat: count for cat, count in cat_rows}}

@app.get("/categories/")
def get_categories(): return {"categories": VALID_CATEGORIES}
