import json

import pytest

pytest.importorskip("fastapi")

import httpx
from fastapi.testclient import TestClient

from hushmask.proxy.config import ConfigError, ProxyConfig, passthrough_config
from hushmask.proxy.server import create_app
from hushmask.proxy.store import AppStore
from tests.test_proxy import FakeUpstream, apps_config

ADMIN = {"X-Hushmask-Admin": "1"}
LOCAL = "http://127.0.0.1:8700"


def admin_client(tmp_path, upstream=None) -> tuple[TestClient, AppStore]:
    store = AppStore.open(tmp_path / "apps.json")
    app = create_app(ProxyConfig({}), store=store, transport=httpx.MockTransport(upstream or FakeUpstream()))
    return TestClient(app, base_url=LOCAL, headers=ADMIN), store


NEW_APP = {
    "name": "spence",
    "upstream_url": "https://upstream.test/v1/",
    "upstream_api_key": "sk-real",
    "preset": "finance",
    "known": ["PERSON=Rahul Sharma", "  "],
}


# -- guards -------------------------------------------------------------------------------------


def test_admin_api_needs_the_custom_header(tmp_path):
    client, _ = admin_client(tmp_path)
    with client:
        assert client.get("/hushmask/api/info", headers={"X-Hushmask-Admin": ""}).status_code == 403


@pytest.mark.parametrize("host", ["evil.example", "192.168.1.5:8700", "attacker.test:8700"])
def test_admin_api_refuses_non_local_hosts(tmp_path, host):
    # DNS rebinding: a page on evil.example resolves its name to 127.0.0.1; the Host header gives it away.
    client, _ = admin_client(tmp_path)
    with client:
        assert client.get("/hushmask/api/info", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("host", ["localhost:8700", "127.0.0.1", "[::1]:8700"])
def test_admin_api_accepts_local_hosts(tmp_path, host):
    client, _ = admin_client(tmp_path)
    with client:
        assert client.get("/hushmask/api/info", headers={"Host": host}).status_code == 200


# -- apps ---------------------------------------------------------------------------------------


def test_create_app_then_use_it_through_the_proxy(tmp_path):
    upstream = FakeUpstream()
    client, _ = admin_client(tmp_path, upstream)
    with client:
        created = client.post("/hushmask/api/apps", json=NEW_APP)
        assert created.status_code == 201
        view = created.json()
        assert view["key"].startswith("hm-spence-")
        assert view["upstream_url"] == "https://upstream.test/v1"
        assert view["known"] == ["PERSON=Rahul Sharma"]
        assert view["api_key_ready"] and view["has_stored_api_key"]
        assert "upstream_api_key" not in view  # the stored provider key is never sent to the browser

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {view['key']}"},
            json={"model": "m", "messages": [{"role": "user", "content": "Rahul Sharma paid"}]},
        )
    assert response.status_code == 200
    assert "Rahul" not in upstream.requests[-1].content.decode()
    assert upstream.requests[-1].headers["authorization"] == "Bearer sk-real"


def test_apps_persist_with_their_secret(tmp_path):
    client, store = admin_client(tmp_path)
    with client:
        key = client.post("/hushmask/api/apps", json=NEW_APP).json()["key"]
    reopened = AppStore.open(tmp_path / "apps.json")
    app = reopened.get("spence")
    assert app.key == key
    assert app.secret == store.get("spence").secret  # same tokens after a restart


def test_update_rotate_delete(tmp_path):
    client, _ = admin_client(tmp_path)
    with client:
        old_key = client.post("/hushmask/api/apps", json=NEW_APP).json()["key"]
        updated = client.put("/hushmask/api/apps/spence", json={"preset": "strict", "upstream_api_key_env": "X_KEY"})
        assert updated.json()["preset"] == "strict"
        assert updated.json()["upstream_api_key_env"] == "X_KEY"
        new_key = client.post("/hushmask/api/apps/spence/rotate-key").json()["key"]
        assert new_key != old_key
        assert client.delete("/hushmask/api/apps/spence").status_code == 204
        assert client.get("/hushmask/api/apps").json() == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({**NEW_APP, "name": "Bad Name"}, "lowercase"),
        ({**NEW_APP, "upstream_url": "ftp://x"}, "http"),
        ({**NEW_APP, "preset": "loose"}, "unknown preset"),
    ],
)
def test_create_validation(tmp_path, body, message):
    client, _ = admin_client(tmp_path)
    with client:
        response = client.post("/hushmask/api/apps", json=body)
    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_duplicate_and_missing_apps(tmp_path):
    client, _ = admin_client(tmp_path)
    with client:
        client.post("/hushmask/api/apps", json=NEW_APP)
        assert client.post("/hushmask/api/apps", json=NEW_APP).status_code == 400
        assert client.put("/hushmask/api/apps/nope", json={}).status_code == 404


def test_config_file_apps_are_read_only():
    app = create_app(apps_config(), transport=httpx.MockTransport(FakeUpstream()))
    with TestClient(app, base_url=LOCAL, headers=ADMIN) as client:
        assert client.get("/hushmask/api/info").json()["editable"] is False
        assert client.put("/hushmask/api/apps/spence", json={"preset": "strict"}).status_code == 400


def test_store_rejects_writes_when_read_only():
    with pytest.raises(ConfigError):
        AppStore().create("x", {"upstream_url": "http://u"})


# -- playground ---------------------------------------------------------------------------------


def test_preview_shows_entities_and_tokens(tmp_path):
    client, _ = admin_client(tmp_path)
    text = "Rahul Sharma paid with 4111 1111 1111 1111"
    with client:
        result = client.post("/hushmask/api/preview", json={"text": text, "known": ["PERSON=Rahul Sharma"]}).json()
    assert [(e["type"], e["text"]) for e in result["entities"]] == [
        ("PERSON", "Rahul Sharma"),
        ("CARD", "4111 1111 1111 1111"),
    ]
    first = result["entities"][0]
    assert text[first["start"] : first["end"]] == "Rahul Sharma"
    assert result["masked"] == f"{first['token']} paid with {result['entities'][1]['token']}"


def test_roundtrip_shows_every_stage(tmp_path):
    client, _ = admin_client(tmp_path)
    with client:
        client.post("/hushmask/api/apps", json=NEW_APP)
        result = client.post(
            "/hushmask/api/roundtrip",
            json={"app": "spence", "model": "m", "text": "Rahul Sharma paid SWIGGY", "instruction": "Summarize."},
        ).json()
    assert result["ok"]
    sent = json.dumps(result["sent_messages"])
    assert "Rahul" not in sent and "SWIGGY" in sent
    assert "PERSON_" in result["masked_answer"]
    assert "Rahul Sharma" in result["restored_answer"]
    assert result["masked_counts"] == {"PERSON": 1}


def test_roundtrip_reports_upstream_errors(tmp_path):
    client, _ = admin_client(tmp_path, FakeUpstream(status=401))
    with client:
        client.post("/hushmask/api/apps", json=NEW_APP)
        result = client.post("/hushmask/api/roundtrip", json={"app": "spence", "model": "m", "text": "hi"}).json()
    assert result == {"ok": False, "status": 401, "error": result["error"], "took_ms": result["took_ms"]}
    assert "upstream says no" in result["error"]


def test_roundtrip_in_passthrough_uses_given_key():
    upstream = FakeUpstream()
    app = create_app(passthrough_config("https://upstream.test/v1"), transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url=LOCAL, headers=ADMIN) as client:
        result = client.post(
            "/hushmask/api/roundtrip", json={"app": "default", "model": "m", "text": "hi", "api_key": "sk-once"}
        ).json()
    assert result["ok"]
    assert upstream.requests[-1].headers["authorization"] == "Bearer sk-once"


def test_unreachable_upstream_is_a_clean_502(tmp_path):
    def down(request):
        raise httpx.ConnectError("refused")

    client, _ = admin_client(tmp_path, down)
    with client:
        key = client.post("/hushmask/api/apps", json=NEW_APP).json()["key"]
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unreachable"
