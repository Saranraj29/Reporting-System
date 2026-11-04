"""Demo data: `python -m app.seed`. Creates a fully populated company so every screen has content.
Login: priya@northwind.dev / Demo@12345 (Manager), asha@northwind.dev (Company Admin), see DEMO_USERS."""

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from .db import new_session
from .models import (
    Client,
    ClientContact,
    DailyStatus,
    Project,
    ProjectMember,
    ReportTemplate,
    Task,
    TaskAssignee,
    Team,
    TeamMember,
    TimeEntry,
    User,
    UserRole,
)
from .security import hash_password
from .services.tenancy import provision_company
from .services.timeutil import company_today

PASSWORD = "Demo@12345"
DOMAIN = "northwind.dev"
DEMO_USERS = [  # (name, local part, role)
    ("Asha Verma", "asha", "Company Admin"),
    ("Rohan Mehta", "rohan", "CEO / CTO"),
    ("Priya Nair", "priya", "Manager"),
    ("Karthik Rao", "karthik", "Team Lead"),
    ("Divya Iyer", "divya", "Team Member"),
    ("Arjun Das", "arjun", "Team Member"),
    ("Meera Pillai", "meera", "Team Member"),
    ("Sanjay Gupta", "sanjay", "Team Lead"),
    ("Nisha Kapoor", "nisha", "Team Member"),
]
TASKS = [  # (title, project, activity, priority, status, eta, assignee locals)
    ("Redesign landing page hero", "Website Revamp", "Design", "high", "done", 12, ["divya"]),
    ("Implement responsive navigation", "Website Revamp", "Development", "medium", "done", 8, ["arjun"]),
    ("Product catalogue API integration", "Website Revamp", "Development", "high", "in_progress", 20, ["arjun", "karthik"]),
    ("Checkout flow usability tests", "Website Revamp", "Testing", "medium", "testing", 10, ["meera"]),
    ("Cart discount rules", "Website Revamp", "Development", "medium", "in_review", 8, ["arjun"]),
    ("Payment gateway sandbox access", "Website Revamp", "Support", "urgent", "blocked", 4, ["karthik"]),
    ("SEO metadata audit", "Website Revamp", "Documentation", "low", "todo", 6, ["divya"]),
    ("Push notification service", "Mobile App", "Development", "high", "in_progress", 24, ["nisha", "sanjay"]),
    ("Onboarding screens design", "Mobile App", "Design", "medium", "done", 14, ["meera"]),
    ("Offline mode sync engine", "Mobile App", "Development", "urgent", "in_progress", 30, ["sanjay"]),
    ("App store release checklist", "Mobile App", "Documentation", "low", "todo", 5, ["nisha"]),
    ("Crash reporting setup", "Mobile App", "Testing", "medium", "done", 6, ["nisha"]),
    ("Biometric login", "Mobile App", "Development", "high", "blocked", 16, ["sanjay", "nisha"]),
    ("CI pipeline caching", "Internal Tools", "Development", "medium", "done", 5, ["karthik"]),
    ("Time-tracking widget feedback", "Internal Tools", "Meeting", "low", "todo", 2, ["divya", "arjun"]),
    ("Weekly sprint review", "Internal Tools", "Meeting", "medium", "in_progress", 3, ["karthik", "sanjay"]),
    ("Migrate staging database", "Internal Tools", "Support", "high", "in_review", 9, ["arjun"]),
]


def run() -> None:
    rnd = random.Random(7)
    anon = new_session()
    existing = anon.execute(text("SELECT id FROM auth_company_by_domain(:d)"), {"d": DOMAIN}).first()
    anon.close()
    if existing:
        print(f"Demo company already exists ({DOMAIN}); nothing to do")
        return
    cid = uuid.uuid4()
    db = new_session(cid)
    company, roles = provision_company(db, "Northwind Labs", DOMAIN, "Asia/Kolkata")
    company.report_email_day = 0
    users: dict[str, User] = {}
    pw = hash_password(PASSWORD)
    for name, local, role in DEMO_USERS:
        u = User(company_id=cid, email=f"{local}@{DOMAIN}", name=name, password_hash=pw, email_verified_at=datetime.now(UTC))
        db.add(u)
        db.flush()
        db.add(UserRole(company_id=cid, user_id=u.id, role_id=roles[role].id))
        users[local] = u
    teams = {
        "Web Squad": (users["karthik"], ["karthik", "divya", "arjun", "meera"]),
        "Mobile Squad": (users["sanjay"], ["sanjay", "nisha"]),
    }
    for tname, (lead, members) in teams.items():
        t = Team(company_id=cid, name=tname, lead_user_id=lead.id)
        db.add(t)
        db.flush()
        db.add_all(TeamMember(company_id=cid, team_id=t.id, user_id=users[m].id) for m in members)
    clients = {
        "Contoso Retail": Client(company_id=cid, name="Contoso Retail", contact_name="Hannah Cole", contact_email="hannah@contoso-retail.com"),
        "Fabrikam": Client(company_id=cid, name="Fabrikam", contact_name="Luis Ortega", contact_email="luis@fabrikam.example"),
    }
    db.add_all(clients.values())
    db.flush()
    db.add_all(ClientContact(company_id=cid, client_id=c.id, name=c.contact_name, email=c.contact_email) for c in clients.values())
    today = company_today(company.timezone)
    projects = {
        "Website Revamp": Project(company_id=cid, name="Website Revamp", client_id=clients["Contoso Retail"].id, start_date=today - timedelta(days=60), end_date=today + timedelta(days=40)),
        "Mobile App": Project(company_id=cid, name="Mobile App", client_id=clients["Fabrikam"].id, start_date=today - timedelta(days=45), end_date=today + timedelta(days=75)),
        "Internal Tools": Project(company_id=cid, name="Internal Tools", start_date=today - timedelta(days=90)),
    }
    db.add_all(projects.values())
    db.flush()
    owners = {"Website Revamp": {"karthik"}, "Mobile App": {"sanjay"}, "Internal Tools": {"karthik", "sanjay"}}  # project owners see every task in the project
    for pname, members in {"Website Revamp": ["karthik", "divya", "arjun", "meera"], "Mobile App": ["sanjay", "nisha"], "Internal Tools": ["karthik", "arjun", "sanjay"]}.items():
        db.add_all(ProjectMember(company_id=cid, project_id=projects[pname].id, user_id=users[m].id, is_owner=m in owners[pname]) for m in members)

    for title, pname, act, prio, status, eta, who in TASKS:
        due = today + timedelta(days=rnd.randint(-4, 14)) if status != "done" else today - timedelta(days=rnd.randint(1, 12))
        if title.startswith("Payment gateway"):
            due = today - timedelta(days=2)  # one overdue + blocked
        done_at = datetime.now(UTC) - timedelta(days=rnd.randint(0, 6), hours=rnd.randint(0, 8)) if status == "done" else None
        t = Task(
            company_id=cid, project_id=projects[pname].id, created_by=users["priya"].id, title=title,
            description=f"{title} for {pname}.", activity_type=act, priority=prio, status=status, eta_hours=eta,
            start_date=today - timedelta(days=rnd.randint(8, 25)), due_date=due, is_blocked=status == "blocked", completed_at=done_at,
            created_at=datetime.now(UTC) - timedelta(days=rnd.randint(8, 25)),
        )
        db.add(t)
        db.flush()
        db.add_all(TaskAssignee(company_id=cid, task_id=t.id, user_id=users[w].id) for w in who)
        if status != "todo":
            for w in who:
                for back in rnd.sample(range(0, 14), k=max(2, round(eta / len(who) / 2.2))):
                    day = today - timedelta(days=back)
                    if day.weekday() < 5:
                        db.add(TimeEntry(company_id=cid, task_id=t.id, user_id=users[w].id, hours=rnd.choice([1, 1.5, 2, 2.5]),
                                         entry_date=day, note=rnd.choice(["", "pairing", "review feedback", "bug fixes"])))
    # two check-ins a day (morning plan + end-of-day update) over the last working days, with realistic gaps
    now = datetime.now(UTC)
    plans = ["Finish the assigned tickets", "Review PRs, then pair on the open bug", "Write tests and update docs", "Sprint planning, then feature work"]
    dones = ["Closed two tickets and reviewed a PR", "Paired on a tricky bug, fixed it", "Added tests, updated the docs", "Planning done, started the next feature"]
    workdays = [today - timedelta(days=i) for i in range(0, 8) if (today - timedelta(days=i)).weekday() < 5]
    for local in ("divya", "arjun", "karthik", "meera", "nisha", "sanjay"):
        for n, day in enumerate(workdays):
            skip_morning = (local == "nisha" and n % 2 == 1) or (local == "sanjay" and day == today)
            skip_eod = (local == "meera" and n % 3 == 1) or (day == today and local in ("divya", "sanjay"))
            if skip_morning and skip_eod:
                continue
            base = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
            db.add(DailyStatus(
                company_id=cid, user_id=users[local].id, status_date=day,
                plan_today="" if skip_morning else plans[(n + len(local)) % len(plans)],
                morning_at=None if skip_morning else (now - timedelta(hours=4, minutes=rnd.randint(0, 50)) if day == today else base + timedelta(hours=9, minutes=rnd.randint(0, 50))),
                did_today="" if skip_eod else dones[(n + len(local)) % len(dones)],
                eod_at=None if skip_eod else (now - timedelta(minutes=rnd.randint(1, 30)) if day == today else base + timedelta(hours=17, minutes=rnd.randint(0, 50))),
                next_up="" if skip_eod else "Pick up the next sprint items.",
                blockers="Waiting on payment sandbox credentials." if local == "karthik" and day == today else "",
            ))
    db.add(ReportTemplate(
        company_id=cid, name="Contoso weekly client update", audience="client", base_report="weekly", format="narrative",
        sections=["Summary", "Work completed", "Hours by area", "Risks and blockers", "Next week"],
        tone_instructions="Formal, no internal names, round hours to the nearest half hour, keep it to one page",
        client_id=clients["Contoso Retail"].id, schedule="weekly",
    ))
    db.add(ReportTemplate(
        company_id=cid, name="Contoso project visibility report", audience="client", base_report="visibility", format="narrative",
        sections=["Sprint goal", "Workflow", "Key achievement"], tone_instructions="Factual and concise, no internal names.",
        client_id=clients["Contoso Retail"].id, schedule="none",
    ))
    db.add(ReportTemplate(
        company_id=cid, name="Leadership visibility report (all projects)", audience="internal", base_report="visibility", format="narrative",
        sections=["Sprint goal", "Workflow", "Key achievement"], tone_instructions="Management summary.", client_id=None, schedule="none",
    ))
    db.add(ReportTemplate(
        company_id=cid, name="Fabrikam monthly summary", audience="client", base_report="monthly", format="bullet_summary",
        sections=["Summary", "Work completed", "Risks and blockers"], tone_instructions="Concise bullets, friendly tone.",
        client_id=clients["Fabrikam"].id, schedule="monthly",
    ))
    db.commit()
    db.close()
    print(f"Seeded {company.name}. Log in as priya@{DOMAIN} (Manager), asha@{DOMAIN} (Admin), karthik@{DOMAIN} (Lead), "
          f"divya@{DOMAIN} (Member) — password {PASSWORD}")


if __name__ == "__main__":
    run()
