import uuid

import pytest


def _unique(suffix: str = "") -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    return {
        "tenant_name": f"Acme-{tag}",
        "email": f"owner-{tag}@acme-{suffix or 'test'}.io",
        "password": "super-secret-passphrase",
    }


@pytest.fixture()
def credentials() -> dict[str, str]:
    return _unique()


def _get_token(client, credentials: dict[str, str]) -> str:
    resp = client.post(
        "/auth/token", data={"username": credentials["email"], "password": credentials["password"]}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestRegisterAndToken:
    def test_register_creates_tenant_and_user(self, client, credentials: dict[str, str]) -> None:
        resp = client.post("/auth/register", json=credentials)
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == credentials["email"]
        assert "password" not in body and "hashed_password" not in body

    def test_register_duplicate_email_conflicts(self, client, credentials: dict[str, str]) -> None:
        client.post("/auth/register", json=credentials)
        resp = client.post("/auth/register", json={**credentials, "tenant_name": "Other"})
        assert resp.status_code == 409

    def test_weak_password_rejected(self, client) -> None:
        resp = client.post("/auth/register", json=_unique() | {"password": "short"})
        assert resp.status_code == 422

    def test_token_with_wrong_password_fails(self, client, credentials: dict[str, str]) -> None:
        client.post("/auth/register", json=credentials)
        resp = client.post(
            "/auth/token",
            data={"username": credentials["email"], "password": "wrong-password-1"},
        )
        assert resp.status_code == 401


class TestProtectedEndpoints:
    def test_me_requires_auth(self, client) -> None:
        assert client.get("/auth/me").status_code == 401

    def test_me_with_jwt(self, client, credentials: dict[str, str]) -> None:
        client.post("/auth/register", json=credentials)
        resp = client.get("/auth/me", headers=_auth_headers(_get_token(client, credentials)))
        assert resp.status_code == 200
        assert uuid.UUID(resp.json()["tenant_id"])

    def test_me_with_garbage_token(self, client) -> None:
        resp = client.get("/auth/me", headers=_auth_headers("not-a-jwt"))
        assert resp.status_code == 401


class TestApiKeys:
    def test_full_api_key_flow(self, client, credentials: dict[str, str]) -> None:
        client.post("/auth/register", json=credentials)
        token = _get_token(client, credentials)

        created = client.post(
            "/auth/api-keys", json={"name": "ci"}, headers=_auth_headers(token)
        )
        assert created.status_code == 201
        raw_key = created.json()["raw_key"]
        assert raw_key.startswith("trg_")

        # Raw key authenticates programmatic access.
        me = client.get("/auth/me", headers={"X-API-Key": raw_key})
        assert me.status_code == 200
        assert me.json()["user_id"] is None

        # Listed keys never expose the raw key or its hash.
        keys = client.get("/auth/api-keys", headers=_auth_headers(token))
        assert keys.status_code == 200
        assert all("raw_key" not in k and "key_hash" not in k for k in keys.json())

        # Revocation: the key stops authenticating and disappears from the list.
        key_id = keys.json()[0]["id"]
        revoked = client.delete(f"/auth/api-keys/{key_id}", headers=_auth_headers(token))
        assert revoked.status_code == 204
        assert client.get("/auth/me", headers={"X-API-Key": raw_key}).status_code == 401
        assert client.get("/auth/api-keys", headers=_auth_headers(token)).json() == []
        assert (
            client.delete(f"/auth/api-keys/{key_id}", headers=_auth_headers(token)).status_code
            == 404
        )

    def test_api_key_cannot_mint_api_keys(self, client, credentials: dict[str, str]) -> None:
        client.post("/auth/register", json=credentials)
        token = _get_token(client, credentials)
        raw_key = client.post(
            "/auth/api-keys", json={"name": "ci"}, headers=_auth_headers(token)
        ).json()["raw_key"]
        resp = client.post(
            "/auth/api-keys", json={"name": "escalate"}, headers={"X-API-Key": raw_key}
        )
        assert resp.status_code == 403

    def test_tenant_isolation_of_key_listing(self, client) -> None:
        creds_a, creds_b = _unique(), _unique()
        for creds in (creds_a, creds_b):
            client.post("/auth/register", json=creds)
        token_a = _get_token(client, creds_a)
        key_a = client.post(
            "/auth/api-keys", json={"name": "a"}, headers=_auth_headers(token_a)
        ).json()["raw_key"]

        token_b = _get_token(client, creds_b)
        keys_via_a = client.get("/auth/api-keys", headers={"X-API-Key": key_a}).json()
        keys_via_b = client.get("/auth/api-keys", headers=_auth_headers(token_b)).json()
        assert keys_via_a and not keys_via_b
