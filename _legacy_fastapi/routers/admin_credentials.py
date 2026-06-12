from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db, cfg, setting_set
from routers.auth import is_admin, session_email
from routers.settings_api import ADMIN_FIELDS, ADMIN_KEYS, MASK, _mask

router = APIRouter()


class AdminCredentialsPayload(BaseModel):
    values: dict[str, str] = {}


@router.get("/api/admin/credentials")
def get_admin_credentials(db: Session = Depends(get_db)):
    if not is_admin(db):
        raise HTTPException(403, "Admin credentials require Google sign-in as egor.alokhin@gmail.com")
    return {
        "email": session_email(db),
        "fields": [
            {"key": key, "label": label, "type": ftype, "secret": secret,
             "value": _mask(cfg(key), secret)}
            for key, label, ftype, secret in ADMIN_FIELDS
        ],
    }


@router.post("/api/admin/credentials")
def save_admin_credentials(body: AdminCredentialsPayload, db: Session = Depends(get_db)):
    if not is_admin(db):
        raise HTTPException(403, "Admin credentials require Google sign-in as egor.alokhin@gmail.com")
    updated = []
    for key, value in body.values.items():
        if key not in ADMIN_KEYS:
            continue
        if not value or value == MASK:
            continue
        setting_set(db, key, value.strip())
        updated.append(key)
    db.commit()
    return {"ok": True, "updated": updated}
