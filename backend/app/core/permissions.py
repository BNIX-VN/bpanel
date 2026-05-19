from enum import StrEnum

from fastapi import HTTPException, status


class Role(StrEnum):
    super_admin = "super_admin"
    admin = "admin"
    user = "user"
    readonly = "readonly"


ROLE_LEVEL = {
    Role.readonly: 1,
    Role.user: 2,
    Role.admin: 3,
    Role.super_admin: 4,
}


def ensure_role(current_role: str, minimum: Role) -> None:
    try:
        role = Role(current_role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid role") from exc
    if ROLE_LEVEL.get(role, 0) < ROLE_LEVEL[minimum]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
