
import pytest

from tests.test_auth import _get_token, _unique  # shared fixtures/helpers


def _register_and_token(client, creds: dict[str, str]) -> str:
    resp = client.post("/auth/register", json=creds)
    assert resp.status_code == 201, resp.text
    return _get_token(client, creds)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


CONTENT = b"# Handbook\n\nEmployees carry over 5 vacation days.\n" * 5


@pytest.fixture()
def token(client) -> str:
    return _register_and_token(client, _unique())


class TestUpload:
    def test_upload_creates_pending_document(self, client, token: str) -> None:
        resp = client.post(
            "/documents",
            files={"file": ("handbook.md", CONTENT, "text/markdown")},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["filename"] == "handbook.md"
        # The live worker may pick the job up immediately, so accept both states.
        assert body["status"] in ("pending", "processing")
        assert len(body["checksum"]) == 64

    def test_duplicate_upload_conflicts(self, client, token: str) -> None:
        headers = _auth(token)
        first = client.post(
            "/documents", files={"file": ("a.md", CONTENT, "text/markdown")}, headers=headers
        )
        assert first.status_code == 201
        second = client.post(
            "/documents", files={"file": ("b.md", CONTENT, "text/markdown")}, headers=headers
        )
        assert second.status_code == 409

    def test_rejected_mime_type(self, client, token: str) -> None:
        resp = client.post(
            "/documents",
            files={"file": ("evil.exe", b"MZ...", "application/x-msdownload")},
            headers=_auth(token),
        )
        assert resp.status_code == 415

    def test_upload_requires_auth(self, client) -> None:
        resp = client.post(
            "/documents", files={"file": ("a.md", CONTENT, "text/markdown")}
        )
        assert resp.status_code == 401


class TestListGetDelete:
    def _upload(self, client, token: str) -> str:
        resp = client.post(
            "/documents",
            files={"file": ("handbook.md", CONTENT, "text/markdown")},
            headers=_auth(token),
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    def test_detail_includes_chunk_count(self, client, token: str) -> None:
        doc_id = self._upload(client, token)
        resp = client.get(f"/documents/{doc_id}", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["chunk_count"] == 0

    def test_delete_then_404(self, client, token: str) -> None:
        doc_id = self._upload(client, token)
        assert client.delete(f"/documents/{doc_id}", headers=_auth(token)).status_code == 204
        assert client.get(f"/documents/{doc_id}", headers=_auth(token)).status_code == 404

    def test_tenant_isolation(self, client, token: str) -> None:
        doc_id = self._upload(client, token)
        other_token = _register_and_token(client, _unique())
        assert client.get(f"/documents/{doc_id}", headers=_auth(other_token)).status_code == 404
        assert (
            client.delete(f"/documents/{doc_id}", headers=_auth(other_token)).status_code == 404
        )
        # Owner still sees it.
        assert client.get("/documents", headers=_auth(token)).status_code == 200
