from types import SimpleNamespace

import pytest

from google.auth.exceptions import RefreshError

from auth.google_auth import _determine_oauth_prompt, start_auth_flow


class _DummyCredentialStore:
    def __init__(self, credentials_by_email=None):
        self._credentials_by_email = credentials_by_email or {}

    def get_credential(self, user_email):
        return self._credentials_by_email.get(user_email)


class _DummySessionStore:
    def __init__(self, user_by_session=None, credentials_by_session=None):
        self._user_by_session = user_by_session or {}
        self._credentials_by_session = credentials_by_session or {}

    def get_user_by_mcp_session(self, mcp_session_id):
        return self._user_by_session.get(mcp_session_id)

    def get_credentials_by_mcp_session(self, mcp_session_id):
        return self._credentials_by_session.get(mcp_session_id)


def _credentials_with_scopes(scopes, valid=True, refresh_token="fake-token"):
    return SimpleNamespace(scopes=scopes, valid=valid, refresh_token=refresh_token)


@pytest.mark.asyncio
async def test_start_auth_flow_includes_additional_scopes(monkeypatch):
    captured = {}

    class _DummyFlow:
        code_verifier = "verifier"

        def authorization_url(self, **kwargs):
            captured["authorization_kwargs"] = kwargs
            return "https://example.com/auth", None

    class _DummyOAuthStore:
        def store_oauth_state(self, *args, **kwargs):  # noqa: ARG002
            captured["stored_state"] = True

    def fake_create_oauth_flow(**kwargs):
        captured["scopes"] = kwargs["scopes"]
        return _DummyFlow()

    async def fake_determine_prompt(**kwargs):
        captured["prompt_scopes"] = kwargs["required_scopes"]
        return "consent"

    monkeypatch.setattr("auth.google_auth.get_current_scopes", lambda: ["scope.base"])
    monkeypatch.setattr("auth.google_auth.create_oauth_flow", fake_create_oauth_flow)
    monkeypatch.setattr(
        "auth.google_auth._determine_oauth_prompt", fake_determine_prompt
    )
    monkeypatch.setattr("auth.google_auth.get_fastmcp_session_id", lambda: None)
    monkeypatch.setattr(
        "auth.google_auth.get_oauth21_session_store", lambda: _DummyOAuthStore()
    )

    message = await start_auth_flow(
        user_google_email="user@gmail.com",
        service_name="Google Chat",
        redirect_uri="http://localhost:8000/oauth2callback",
        additional_scopes=["scope.extra"],
    )

    assert "https://example.com/auth" in message
    assert set(captured["scopes"]) == {"scope.base", "scope.extra"}
    assert set(captured["prompt_scopes"]) == {"scope.base", "scope.extra"}
    assert captured["authorization_kwargs"]["prompt"] == "consent"
    assert captured["stored_state"] is True


@pytest.mark.asyncio
async def test_prompt_select_account_when_existing_credentials_cover_scopes(
    monkeypatch,
):
    required_scopes = ["scope.a", "scope.b"]
    monkeypatch.setattr(
        "auth.google_auth.get_oauth21_session_store",
        lambda: _DummySessionStore(),
    )
    monkeypatch.setattr(
        "auth.google_auth.get_credential_store",
        lambda: _DummyCredentialStore(
            {"user@gmail.com": _credentials_with_scopes(required_scopes, valid=True)}
        ),
    )
    monkeypatch.setattr("auth.google_auth.is_stateless_mode", lambda: False)

    prompt = await _determine_oauth_prompt(
        user_google_email="user@gmail.com",
        required_scopes=required_scopes,
        session_id=None,
    )

    assert prompt == "select_account"


@pytest.mark.asyncio
async def test_prompt_consent_when_credentials_revoked(monkeypatch):
    """When credentials have required scopes but refresh fails (revoked),
    prompt must be 'consent' so Google performs full re-authorization."""
    required_scopes = ["scope.a", "scope.b"]

    def _raise_on_refresh(_self, _request):
        raise RefreshError("invalid_grant: Token has been revoked")

    creds = _credentials_with_scopes(required_scopes, valid=False)
    creds.refresh = _raise_on_refresh.__get__(creds)

    monkeypatch.setattr(
        "auth.google_auth.get_oauth21_session_store",
        lambda: _DummySessionStore(),
    )
    monkeypatch.setattr(
        "auth.google_auth.get_credential_store",
        lambda: _DummyCredentialStore({"user@gmail.com": creds}),
    )
    monkeypatch.setattr("auth.google_auth.is_stateless_mode", lambda: False)

    prompt = await _determine_oauth_prompt(
        user_google_email="user@gmail.com",
        required_scopes=required_scopes,
        session_id=None,
    )

    assert prompt == "consent"


@pytest.mark.asyncio
async def test_prompt_consent_when_existing_credentials_missing_scopes(monkeypatch):
    monkeypatch.setattr(
        "auth.google_auth.get_oauth21_session_store",
        lambda: _DummySessionStore(),
    )
    monkeypatch.setattr(
        "auth.google_auth.get_credential_store",
        lambda: _DummyCredentialStore(
            {"user@gmail.com": _credentials_with_scopes(["scope.a"])}
        ),
    )
    monkeypatch.setattr("auth.google_auth.is_stateless_mode", lambda: False)

    prompt = await _determine_oauth_prompt(
        user_google_email="user@gmail.com",
        required_scopes=["scope.a", "scope.b"],
        session_id=None,
    )

    assert prompt == "consent"


@pytest.mark.asyncio
async def test_prompt_consent_when_no_existing_credentials(monkeypatch):
    monkeypatch.setattr(
        "auth.google_auth.get_oauth21_session_store",
        lambda: _DummySessionStore(),
    )
    monkeypatch.setattr(
        "auth.google_auth.get_credential_store",
        lambda: _DummyCredentialStore(),
    )
    monkeypatch.setattr("auth.google_auth.is_stateless_mode", lambda: False)

    prompt = await _determine_oauth_prompt(
        user_google_email="new_user@gmail.com",
        required_scopes=["scope.a"],
        session_id=None,
    )

    assert prompt == "consent"


@pytest.mark.asyncio
async def test_prompt_uses_session_mapping_when_email_not_provided(monkeypatch):
    session_id = "session-123"
    required_scopes = ["scope.a"]
    monkeypatch.setattr(
        "auth.google_auth.get_oauth21_session_store",
        lambda: _DummySessionStore(
            user_by_session={session_id: "mapped@gmail.com"},
            credentials_by_session={
                session_id: _credentials_with_scopes(required_scopes, valid=True)
            },
        ),
    )
    monkeypatch.setattr(
        "auth.google_auth.get_credential_store",
        lambda: _DummyCredentialStore(),
    )
    monkeypatch.setattr("auth.google_auth.is_stateless_mode", lambda: False)

    prompt = await _determine_oauth_prompt(
        user_google_email=None,
        required_scopes=required_scopes,
        session_id=session_id,
    )

    assert prompt == "select_account"
