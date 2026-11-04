"""ORM mapping of the schema created by alembic/versions/0001_initial.sql."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _cid() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)


def _fk(table: str, nullable: bool = False, ondelete: str = "CASCADE"):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable)


class Stamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Company(Base, Stamps):
    __tablename__ = "companies"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text)
    email_domain: Mapped[str] = mapped_column(Text, unique=True)
    slack_webhook_url: Mapped[str | None] = mapped_column(Text)
    report_email_day: Mapped[int | None] = mapped_column(SmallInteger, default=0)
    timezone: Mapped[str] = mapped_column(Text, default="UTC")


class User(Base, Stamps):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    email: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    google_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    refresh_version: Mapped[int] = mapped_column(Integer, default=0)


class Team(Base, Stamps):
    __tablename__ = "teams"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    name: Mapped[str] = mapped_column(Text)
    lead_user_id: Mapped[uuid.UUID | None] = _fk("users", True, "SET NULL")


class TeamMember(Base, Stamps):
    __tablename__ = "team_members"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    team_id: Mapped[uuid.UUID] = _fk("teams")
    user_id: Mapped[uuid.UUID] = _fk("users")


class Permission(Base):
    __tablename__ = "permissions"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")


class Role(Base, Stamps):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    company_id: Mapped[uuid.UUID] = _cid()
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True)
    permission_key: Mapped[str] = mapped_column(Text, ForeignKey("permissions.key"), primary_key=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    company_id: Mapped[uuid.UUID] = _cid()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True)


class Client(Base, Stamps):
    __tablename__ = "clients"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    name: Mapped[str] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(Text)


class ClientContact(Base, Stamps):
    __tablename__ = "client_contacts"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    client_id: Mapped[uuid.UUID] = _fk("clients")
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)


class Project(Base, Stamps):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    name: Mapped[str] = mapped_column(Text)
    client_id: Mapped[uuid.UUID | None] = _fk("clients", True, "SET NULL")
    status: Mapped[str] = mapped_column(Text, default="active")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class ProjectMember(Base):
    __tablename__ = "project_members"
    company_id: Mapped[uuid.UUID] = _cid()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Base, Stamps):
    __tablename__ = "tasks"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    project_id: Mapped[uuid.UUID] = _fk("projects")
    created_by: Mapped[uuid.UUID | None] = _fk("users", True, "SET NULL")
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    activity_type: Mapped[str] = mapped_column(Text, default="Development")
    priority: Mapped[str] = mapped_column(Text, default="medium")
    status: Mapped[str] = mapped_column(Text, default="todo")
    eta_hours: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class TaskAssignee(Base):
    __tablename__ = "task_assignees"
    company_id: Mapped[uuid.UUID] = _cid()
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)


class TimeEntry(Base, Stamps):
    __tablename__ = "time_entries"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    task_id: Mapped[uuid.UUID] = _fk("tasks")
    user_id: Mapped[uuid.UUID] = _fk("users")
    hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    entry_date: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, default="")


class TaskComment(Base, Stamps):
    __tablename__ = "task_comments"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    task_id: Mapped[uuid.UUID] = _fk("tasks")
    user_id: Mapped[uuid.UUID] = _fk("users")
    body: Mapped[str] = mapped_column(Text)


class DailyStatus(Base, Stamps):
    __tablename__ = "daily_status"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    user_id: Mapped[uuid.UUID] = _fk("users")
    status_date: Mapped[date] = mapped_column(Date)
    did_today: Mapped[str] = mapped_column(Text, default="")
    next_up: Mapped[str] = mapped_column(Text, default="")
    blockers: Mapped[str] = mapped_column(Text, default="")


class TaskFieldDefinition(Base, Stamps):
    __tablename__ = "task_field_definitions"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    key: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    options: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class ReportTemplate(Base, Stamps):
    __tablename__ = "report_templates"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    name: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(Text, default="client")
    base_report: Mapped[str] = mapped_column(Text, default="weekly")
    format: Mapped[str] = mapped_column(Text, default="narrative")
    sections: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    tone_instructions: Mapped[str] = mapped_column(Text, default="")
    client_id: Mapped[uuid.UUID | None] = _fk("clients", True, "SET NULL")
    schedule: Mapped[str] = mapped_column(Text, default="none")


class ReportRun(Base, Stamps):
    __tablename__ = "report_runs"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    template_id: Mapped[uuid.UUID | None] = _fk("report_templates", True, "SET NULL")
    report_key: Mapped[str] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    scope_user_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    requested_by: Mapped[uuid.UUID | None] = _fk("users", True, "SET NULL")
    status: Mapped[str] = mapped_column(Text, default="queued")
    export_format: Mapped[str | None] = mapped_column(Text)
    figures: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ai_text: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    ai_provider: Mapped[str | None] = mapped_column(Text)
    redraft_note: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = _fk("users", True, "SET NULL")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_url_pdf: Mapped[str | None] = mapped_column(Text)
    file_url_xlsx: Mapped[str | None] = mapped_column(Text)
    file_url_docx: Mapped[str | None] = mapped_column(Text)


class ReportShare(Base, Stamps):
    __tablename__ = "report_shares"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    report_run_id: Mapped[uuid.UUID] = _fk("report_runs")
    client_id: Mapped[uuid.UUID | None] = _fk("clients", True, "SET NULL")
    recipient_email: Mapped[str] = mapped_column(Text)
    token: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationLog(Base, Stamps):
    __tablename__ = "notification_log"
    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _cid()
    user_id: Mapped[uuid.UUID | None] = _fk("users", True, "SET NULL")
    kind: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="sent")
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(Text, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
