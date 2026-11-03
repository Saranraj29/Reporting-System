from .conftest import PASSWORD, Api, login, signup_admin


def reg(client, email, **kw):
    return client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "name": "Test User", **kw})


def test_first_user_creates_company_and_becomes_admin(client):
    admin = signup_admin(client)
    me = admin.get("/me").json()
    assert me["company"]["name"] == "Acme Corp"
    assert [r["name"] for r in me["roles"]] == ["Company Admin"]
    assert "user.manage" in me["permissions"]
    assert "report.performance.view.all" not in me["permissions"]  # per design, admins have no performance reports


def test_second_user_on_same_domain_joins_as_team_member_after_verification(client):
    signup_admin(client)
    r = reg(client, "jo@acme.com")
    assert r.status_code == 201 and r.json()["verification_required"]
    # unverified: cannot log in, data stays hidden
    bad = client.post("/api/v1/auth/login", json={"email": "jo@acme.com", "password": PASSWORD})
    assert bad.status_code == 403 and bad.json()["code"] == "email_not_verified"
    client.post("/api/v1/auth/verify-email", json={"token": r.json()["dev_verification_token"]}).raise_for_status()
    jo = login(client, "jo@acme.com")
    assert [x["name"] for x in jo.get("/me").json()["roles"]] == ["Team Member"]
    assert jo.get("/me").json()["company"]["name"] == "Acme Corp"


def test_unknown_domain_requires_company_name(client):
    r = reg(client, "x@newco.io")
    assert r.status_code == 409 and r.json()["code"] == "company_required"


def test_public_domains_need_an_invite(client):
    r = reg(client, "someone@gmail.com", company_name="Nope")
    assert r.status_code == 400 and r.json()["code"] == "invite_required"
    assert client.get("/api/v1/auth/domain-check", params={"email": "x@gmail.com"}).json()["status"] == "invite_required"


def test_domain_check(client):
    assert client.get("/api/v1/auth/domain-check", params={"email": "a@acme.com"}).json()["status"] == "create"
    signup_admin(client)
    j = client.get("/api/v1/auth/domain-check", params={"email": "a@acme.com"}).json()
    assert j == {"status": "join", "company_name": "Acme Corp"}


def test_duplicate_email_rejected(client):
    signup_admin(client)
    assert reg(client, "admin@acme.com").status_code == 409


def test_invite_flow_allows_public_domain(client):
    admin = signup_admin(client)
    inv = admin.post("/users/invite", {"email": "freelancer@gmail.com"})
    assert inv.status_code == 201
    token = inv.json()["dev_invite_link"].split("invite=")[1]
    r = reg(client, "freelancer@gmail.com", invite_token=token)
    assert r.status_code == 201 and r.json()["verification_required"] is False
    f = login(client, "freelancer@gmail.com")
    assert f.get("/me").json()["company"]["name"] == "Acme Corp"
    # token is bound to the invited address
    assert reg(client, "other@gmail.com", invite_token=token).json()["code"] == "invalid_invite"


def test_refresh_rotates_and_logout_revokes(client):
    signup_admin(client)
    r = client.post("/api/v1/auth/login", json={"email": "admin@acme.com", "password": PASSWORD})
    cookie = r.cookies.get("refresh_token")
    assert cookie
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "path=/api/v1/auth" in set_cookie
    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    assert Api(client, refreshed.json()["access_token"]).get("/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("refresh_token", cookie)  # replaying the old cookie must fail after logout
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_wrong_password_and_missing_token(client):
    signup_admin(client)
    r = client.post("/api/v1/auth/login", json={"email": "admin@acme.com", "password": "nope-nope-nope"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    r = client.get("/api/v1/me")
    assert r.status_code == 401 and set(r.json()) == {"code", "message", "details"}


def test_password_reset_is_single_use(client):
    signup_admin(client)
    token = client.post("/api/v1/auth/forgot-password", json={"email": "admin@acme.com"}).json()["dev_reset_token"]
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": "BrandNew!pass1"}).status_code == 200
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": "Another!pass22"}).status_code == 400
    assert client.post("/api/v1/auth/login", json={"email": "admin@acme.com", "password": PASSWORD}).status_code == 401
    assert login(client, "admin@acme.com", "BrandNew!pass1")


def test_forgot_password_does_not_reveal_unknown_emails(client):
    r = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@nowhere.com"})
    assert r.status_code == 200 and "dev_reset_token" not in r.json()


def test_google_signin_creates_and_logs_in(client, monkeypatch):
    from app.routers import auth

    monkeypatch.setattr(auth, "verify_google_credential",
                        lambda c: {"email": "gina@zeta.io", "email_verified": True, "sub": "g-1", "name": "Gina Z"})
    r = client.post("/api/v1/auth/google", json={"credential": "x", "company_name": "Zeta"})
    assert r.status_code == 200
    me = Api(client, r.json()["access_token"]).get("/me").json()
    assert me["company"]["name"] == "Zeta" and me["roles"][0]["name"] == "Company Admin"
    again = client.post("/api/v1/auth/google", json={"credential": "x"})
    assert again.status_code == 200  # existing account: plain login


def test_google_requires_verified_email(client, monkeypatch):
    from app.routers import auth

    monkeypatch.setattr(auth, "verify_google_credential", lambda c: {"email": "a@b.io", "email_verified": False, "sub": "1"})
    assert client.post("/api/v1/auth/google", json={"credential": "x"}).status_code == 401


def test_auth_rate_limit(client, monkeypatch):
    monkeypatch.setenv("AUTH_RATE_LIMIT_PER_MIN", "3")
    from app.config import get_settings

    get_settings.cache_clear()
    codes = [client.post("/api/v1/auth/login", json={"email": "a@acme.com", "password": "x" * 9}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429
