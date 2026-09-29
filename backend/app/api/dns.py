"""DNS Manager: zones and records on this server's PowerDNS (services/dns.py).

Every route needs the addon. An administrator sees and edits every zone and
the settings; a customer sees and edits the zones of their own websites, and
cannot create zones - a zone comes with a website, or from an administrator.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_admin_role
from app.models.entities import User
from app.services import addons, dns, server_network
from app.services.audit import log_action

router = APIRouter(prefix="/dns", tags=["dns"], dependencies=[Depends(addons.require_dns)])


class RecordIn(BaseModel):
    name: str = Field(default="@", max_length=253)
    type: str = Field(max_length=10)
    ttl: int = Field(default=dns.DEFAULT_TTL, ge=dns.MIN_TTL, le=dns.MAX_TTL)
    content: str = Field(max_length=4096)
    priority: int | None = Field(default=None, ge=0, le=65535)


class RecordChange(BaseModel):
    original: RecordIn
    record: RecordIn


class ZoneIn(BaseModel):
    name: str = Field(max_length=253)
    owner_id: int | None = None


class SettingsIn(BaseModel):
    nameservers: list[str] = Field(default_factory=list, max_length=4)
    zone_ip: str = Field(default="", max_length=45)
    ttl: int = Field(default=dns.DEFAULT_TTL, ge=dns.MIN_TTL, le=dns.MAX_TTL)
    auto_zone: bool = True


def _answer(action):
    """Run a DNS change and turn its failures into HTTP answers."""
    try:
        return action()
    except dns.DnsInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except dns.DnsError as exc:
        raise HTTPException(status_code=404 if exc.status == 404 else 502, detail=str(exc)) from exc


@router.get("/zones")
def list_zones(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    return {
        "zones": _answer(lambda: dns.list_zones(db, current_user)),
        "nameservers": dns.settings()["nameservers"],
        "can_manage": is_admin_role(current_user.role),
    }


@router.post("/zones")
def create_zone(payload: ZoneIn, request: Request, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    if payload.owner_id is not None and not db.query(User).filter(User.id == payload.owner_id).first():
        raise HTTPException(status_code=400, detail="That account does not exist.")
    zone = _answer(lambda: dns.create_zone(db, payload.name, payload.owner_id))
    log_action(db, current_user.id, "dns_create_zone", zone, request=request)
    return {"zone": zone, "message": "Zone created."}


@router.delete("/zones/{zone}")
def delete_zone(zone: str, request: Request, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    name = _answer(lambda: dns.may_edit(db, current_user, zone))
    _answer(lambda: dns.delete_zone(db, name))
    log_action(db, current_user.id, "dns_delete_zone", name, request=request)
    return {"zone": name, "message": "Zone deleted."}


@router.get("/zones/{zone}/records")
def list_records(zone: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    name = _answer(lambda: dns.may_edit(db, current_user, zone))
    return {"zone": name, "records": _answer(lambda: dns.records(name))}


@router.post("/zones/{zone}/records")
def add_record(zone: str, payload: RecordIn, request: Request, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    name = _answer(lambda: dns.may_edit(db, current_user, zone))
    admin = is_admin_role(current_user.role)
    _answer(lambda: dns.add_record(name, payload.model_dump(), admin=admin))
    log_action(db, current_user.id, "dns_add_record", name, f"{payload.type} {payload.name}", request=request)
    return {"zone": name, "records": _answer(lambda: dns.records(name)), "message": "Record added."}


@router.put("/zones/{zone}/records")
def update_record(zone: str, payload: RecordChange, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    name = _answer(lambda: dns.may_edit(db, current_user, zone))
    admin = is_admin_role(current_user.role)
    _answer(lambda: dns.update_record(name, payload.original.model_dump(), payload.record.model_dump(), admin=admin))
    log_action(db, current_user.id, "dns_update_record", name, f"{payload.record.type} {payload.record.name}", request=request)
    return {"zone": name, "records": _answer(lambda: dns.records(name)), "message": "Record saved."}


@router.post("/zones/{zone}/records/delete")
def delete_record(zone: str, payload: RecordIn, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    name = _answer(lambda: dns.may_edit(db, current_user, zone))
    admin = is_admin_role(current_user.role)
    _answer(lambda: dns.delete_record(name, payload.model_dump(), admin=admin))
    log_action(db, current_user.id, "dns_delete_record", name, f"{payload.type} {payload.name}", request=request)
    return {"zone": name, "records": _answer(lambda: dns.records(name)), "message": "Record deleted."}


@router.get("/settings")
def read_settings(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return {**dns.settings(), "server": dns.server_status(), "server_ipv4": server_network.ipv4_addresses()}


@router.put("/settings")
def save_settings(payload: SettingsIn, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    saved = _answer(lambda: dns.save_settings(payload.nameservers, payload.zone_ip, payload.ttl, payload.auto_zone))
    log_action(db, current_user.id, "dns_settings", ", ".join(saved["nameservers"]), request=request)
    return {**saved, "message": "DNS settings saved."}
