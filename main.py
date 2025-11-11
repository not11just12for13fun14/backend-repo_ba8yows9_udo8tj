import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from bson.objectid import ObjectId

from database import db, create_document, get_documents
from schemas import Organization, Admin, Event

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helpers
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def sha256_hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


# Utility to convert Mongo docs to JSON serializable dicts

def serialize_doc(doc):
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id"))
    # Convert datetimes
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.astimezone(timezone.utc).isoformat()
    return doc


@app.get("/")
def read_root():
    return {"message": "Event Platform Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = getattr(db, "name", None) or "❌ Not Set"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# Auth endpoints
@app.post("/auth/admin/login")
def admin_login(payload: LoginRequest):
    admin = db["admin"].find_one({"email": payload.email}) if db else None
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if admin.get("password_hash") != sha256_hash(payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": str(admin.get("_id")), "email": admin.get("email"), "name": admin.get("name")}


class OrgRegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    description: Optional[str] = None
    website: Optional[str] = None


@app.post("/auth/org/register")
def org_register(payload: OrgRegisterRequest):
    if db["organization"].find_one({"email": payload.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    org = Organization(
        name=payload.name,
        email=payload.email,
        password_hash=sha256_hash(payload.password),
        verified=False,
        description=payload.description,
        website=payload.website,
    )
    org_id = create_document("organization", org)
    return {"id": org_id, "verified": False}


@app.post("/auth/org/login")
def org_login(payload: LoginRequest):
    org = db["organization"].find_one({"email": payload.email})
    if not org:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if org.get("password_hash") != sha256_hash(payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": str(org.get("_id")), "email": org.get("email"), "verified": org.get("verified", False), "name": org.get("name")}


# Admin verifies organization
class VerifyOrgRequest(BaseModel):
    org_id: str
    verified: bool = True


@app.post("/admin/verify-organization")
def verify_organization(payload: VerifyOrgRequest):
    try:
        oid = ObjectId(payload.org_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid organization id")
    result = db["organization"].update_one({"_id": oid}, {"$set": {"verified": payload.verified}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"success": True}


# Event creation
class EventCreateRequest(BaseModel):
    title: str
    description: str
    poster_url: Optional[str] = None
    google_form_url: Optional[str] = None
    venue: str
    event_start: datetime
    event_end: Optional[datetime] = None
    registration_start: datetime
    registration_end: datetime
    category: str
    organization_token: str  # org id returned by login


@app.post("/events")
def create_event(payload: EventCreateRequest):
    # find org
    try:
        org_oid = ObjectId(payload.organization_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid organization token")

    org = db["organization"].find_one({"_id": org_oid})
    if not org:
        raise HTTPException(status_code=401, detail="Invalid organization token")

    # Approval logic: auto-approve if org verified, else pending
    is_verified = org.get("verified", False)

    event = Event(
        title=payload.title,
        description=payload.description,
        poster_url=payload.poster_url,
        google_form_url=payload.google_form_url,
        venue=payload.venue,
        event_start=payload.event_start,
        event_end=payload.event_end,
        registration_start=payload.registration_start,
        registration_end=payload.registration_end,
        category=payload.category,
        organization_id=str(org["_id"]),
        organization_name=org.get("name"),
        approved=is_verified,  # auto if verified
        approved_by=None,
        is_org_verified=is_verified,
    )

    event_id = create_document("event", event)
    return {"id": event_id, "approved": is_verified}


class ApproveEventRequest(BaseModel):
    event_id: str
    approve: bool = True


@app.post("/admin/approve-event")
def approve_event(payload: ApproveEventRequest):
    try:
        eid = ObjectId(payload.event_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid event id")
    result = db["event"].update_one({"_id": eid}, {"$set": {"approved": payload.approve, "approved_by": "admin"}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"success": True}


# Public listing with sorting and filtering
@app.get("/events")
def list_events(
    category: Optional[str] = None,
    sort: Optional[str] = "time",
    registration_window: Optional[str] = None,  # open | upcoming | closed
    limit: int = 100,
):
    now = datetime.now(timezone.utc)
    q: dict = {"approved": True}
    if category:
        q["category"] = category
    if registration_window == "open":
        q["registration_start"] = {"$lte": now}
        q["registration_end"] = {"$gte": now}
    elif registration_window == "upcoming":
        q["registration_start"] = {"$gt": now}
    elif registration_window == "closed":
        q["registration_end"] = {"$lt": now}

    cursor = db["event"].find(q)

    # Sorting
    if sort == "time":
        cursor = cursor.sort([("registration_start", 1), ("event_start", 1)])
    elif sort == "recent":
        cursor = cursor.sort("created_at", -1)

    cursor = cursor.limit(min(max(limit, 1), 500))

    docs = [serialize_doc(d) for d in cursor]

    # Reorder: currently open first, then upcoming, then closed
    open_events = [d for d in docs if d["registration_start"] <= now.isoformat() <= d["registration_end"]]
    upcoming_events = [d for d in docs if d["registration_start"] > now.isoformat()]
    closed_events = [d for d in docs if d["registration_end"] < now.isoformat()]

    return {
        "open": open_events,
        "upcoming": upcoming_events,
        "closed": closed_events,
        "count": len(docs)
    }


@app.get("/events/categories")
def list_categories():
    # Aggregate distinct categories from events
    categories = db["event"].distinct("category", {"approved": True})
    return sorted([c for c in categories if c])


# Seed one admin if none exists to ease testing
@app.post("/seed-admin")
def seed_admin(email: EmailStr, password: str, name: Optional[str] = None):
    if db["admin"].find_one({"email": email}):
        return {"created": False}
    admin = Admin(email=email, password_hash=sha256_hash(password), name=name)
    admin_id = create_document("admin", admin)
    return {"created": True, "id": admin_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
