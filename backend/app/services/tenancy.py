import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import Company, Permission, Role, RolePermission, TaskFieldDefinition
from ..perms import PERMISSIONS, SEEDED_ROLES

ACTIVITY_TYPES = ["Development", "Design", "Testing", "Meeting", "Support", "Documentation", "Other"]

BUILTIN_FIELDS = [
    ("description", "Description", "text", []),
    ("activity_type", "Activity type", "select", ACTIVITY_TYPES),
    ("priority", "Priority", "select", ["low", "medium", "high", "urgent"]),
    ("eta_hours", "ETA (hours)", "number", []),
    ("start_date", "Start date", "date", []),
    ("due_date", "Due date", "date", []),
]


def sync_permissions(db: Session) -> None:
    """The global permission list is owned by code; insert anything new."""
    rows = [{"key": k, "description": d} for k, d in PERMISSIONS.items()]
    db.execute(pg_insert(Permission).values(rows).on_conflict_do_nothing(index_elements=["key"]))


def provision_company(db: Session, name: str, domain: str, timezone: str = "UTC") -> tuple[Company, dict[str, Role]]:
    """Creates a company with the seeded roles and built-in task fields.
    `db` must be a tenant session already scoped to the new company id."""
    cid = uuid.UUID(db.info["company_id"])
    sync_permissions(db)
    company = Company(id=cid, name=name, email_domain=domain.lower(), timezone=timezone)
    db.add(company)
    db.flush()
    roles: dict[str, Role] = {}
    for role_name, (desc, keys) in SEEDED_ROLES.items():
        role = Role(company_id=cid, name=role_name, description=desc)
        db.add(role)
        db.flush()
        db.add_all(RolePermission(company_id=cid, role_id=role.id, permission_key=k) for k in keys)
        roles[role_name] = role
    db.add_all(
        TaskFieldDefinition(company_id=cid, key=k, label=lbl, type=t, options=opts, is_builtin=True)
        for k, lbl, t, opts in BUILTIN_FIELDS
    )
    db.flush()
    return company, roles
