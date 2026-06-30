from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from fastapi.middleware.cors import CORSMiddleware

# ── Database Setup ────────────────────────────────────────────────────────────
engine = create_engine("sqlite:///./routine.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

VALID_CATEGORIES = ["Study", "Food", "Sleep", "Exercise", "Work", "Personal", "Health", "Other"]

class Pin(Base):
    __tablename__ = "pins"
    id             = Column(Integer, primary_key=True, index=True)
    note           = Column(String, nullable=False)
    category       = Column(String, default="Other")
    scheduled_time = Column(DateTime, default=datetime.utcnow)
    completed      = Column(Boolean, default=False)
    created_at     = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Personal Routine Tracker API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Schemas ───────────────────────────────────────────────────────────────────
class PinCreate(BaseModel):
    note:           str
    category:       str = "Other"
    scheduled_time: datetime

class PinUpdate(BaseModel):
    note:           Optional[str]      = None
    category:       Optional[str]      = None
    scheduled_time: Optional[datetime] = None
    completed:      Optional[bool]     = None

class PinOut(BaseModel):
    id:             int
    note:           str
    category:       str
    scheduled_time: datetime
    completed:      bool
    created_at:     datetime

    class Config:
        from_attributes = True

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Routine Tracker API v2 is running 🚀"}


@app.post("/pins/", response_model=PinOut)
def create_pin(pin: PinCreate):
    if pin.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Choose from: {VALID_CATEGORIES}")
    db = SessionLocal()
    new_pin = Pin(
        note=pin.note,
        category=pin.category,
        scheduled_time=pin.scheduled_time,
        created_at=datetime.utcnow(),
    )
    db.add(new_pin)
    db.commit()
    db.refresh(new_pin)
    db.close()
    return new_pin


@app.get("/pins/", response_model=list[PinOut])
def get_pins(
    filter_date: Optional[str] = None,
    category:    Optional[str] = None,
    completed:   Optional[bool] = None,
):
    db = SessionLocal()
    query = db.query(Pin)
    if filter_date:
        query = query.filter(Pin.scheduled_time.like(f"{filter_date}%"))
    if category:
        query = query.filter(Pin.category == category)
    if completed is not None:
        query = query.filter(Pin.completed == completed)
    pins = query.order_by(Pin.scheduled_time.asc()).all()
    db.close()
    return pins


@app.get("/pins/{pin_id}", response_model=PinOut)
def get_pin(pin_id: int):
    db = SessionLocal()
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    db.close()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    return pin


@app.put("/pins/{pin_id}", response_model=PinOut)
def update_pin(pin_id: int, updates: PinUpdate):
    db = SessionLocal()
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    if not pin:
        db.close()
        raise HTTPException(status_code=404, detail="Pin not found")
    if updates.note is not None:
        pin.note = updates.note
    if updates.category is not None:
        if updates.category not in VALID_CATEGORIES:
            db.close()
            raise HTTPException(status_code=400, detail=f"Invalid category. Choose from: {VALID_CATEGORIES}")
        pin.category = updates.category
    if updates.scheduled_time is not None:
        pin.scheduled_time = updates.scheduled_time
    if updates.completed is not None:
        pin.completed = updates.completed
    db.commit()
    db.refresh(pin)
    db.close()
    return pin


@app.patch("/pins/{pin_id}/complete", response_model=PinOut)
def toggle_complete(pin_id: int):
    db = SessionLocal()
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    if not pin:
        db.close()
        raise HTTPException(status_code=404, detail="Pin not found")
    pin.completed = not pin.completed
    db.commit()
    db.refresh(pin)
    db.close()
    return pin


@app.delete("/pins/{pin_id}")
def delete_pin(pin_id: int):
    db = SessionLocal()
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    if not pin:
        db.close()
        raise HTTPException(status_code=404, detail="Pin not found")
    db.delete(pin)
    db.commit()
    db.close()
    return {"status": "success", "deleted_id": pin_id}


@app.get("/stats/")
def get_stats(filter_date: Optional[str] = None):
    db = SessionLocal()
    query = db.query(Pin)
    if filter_date:
        query = query.filter(Pin.scheduled_time.like(f"{filter_date}%"))

    total     = query.count()
    completed = query.filter(Pin.completed == True).count()
    pending   = total - completed

    # Per-category breakdown
    cat_rows = (
        db.query(Pin.category, func.count(Pin.id))
        .filter(Pin.scheduled_time.like(f"{filter_date}%") if filter_date else True)
        .group_by(Pin.category)
        .all()
    )
    by_category = {cat: count for cat, count in cat_rows}

    db.close()
    return {
        "total":       total,
        "completed":   completed,
        "pending":     pending,
        "completion_pct": round((completed / total * 100) if total else 0, 1),
        "by_category": by_category,
    }


@app.get("/categories/")
def get_categories():
    return {"categories": VALID_CATEGORIES}
