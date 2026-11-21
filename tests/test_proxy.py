import json
import re

import pytest

pytest.importorskip("fastapi")

import httpx
from fastapi.testclient import TestClient

from hushmask import EntityType, KnownValue, Masker
from hushmask.proxy import ConfigError, load_config, mask_request, passthrough_config, restore_response, to_sse
from hushmask.proxy.config import AppConfig, ProxyConfig
from hushmask.proxy.openai import PLACEHOLDER_NOTE, UnmaskableContent
from hushmask.proxy.server import create_app

TOKEN = re.compile(r"\b[A-Z]+_[0-9a-f]{6}(?:_\d+)?\b")
USER_TEXT = "Rahul Sharma paid 450.00 to SWIGGY with card 4111 1111 1111 1111. Email rahul@example.com"


class FakeUpstream:
    """Echoes the tokens it received back in its answer, and records every request."""

    def __init__(self, reply=None, status=200):
        self.requests: list[httpx.Request] = []
        self.reply = reply
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "fake-model"}]})
        body = json.loads(request.content)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "upstream says no"}})
        user = next(m for m in reversed(body["messages"]) if m["role"] == "user")["content"]
        tokens = TOKEN.findall(user)
        content = self.reply(tokens) if self.reply else f"Summary: {' and '.join(tokens)} spent money at SWIGGY."
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    @property
    def last_body(self) -> dict:
        return json.loads(self.requests[-1].content)


def client_for(config: ProxyConfig, upstream: FakeUpstream) -> TestClient:
    return TestClient(create_app(config, transport=httpx.MockTransport(upstream)))


def apps_config(**overrides) -> ProxyConfig:
    app = AppConfig(
        name="spence",
        key="hm-spence",
        upstream_url="https://upstream.test/v1",
        upstream_api_key="sk-real-provider-key",
        preset="finance",
        known=(KnownValue("Rahul Sharma", EntityType.PERSON),),
        **overrides,
    )
    return ProxyConfig({"spence": app})


def chat(client: TestClient, content: str = USER_TEXT, key: str = "hm-spence", **extra):
    return client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "m", "messages": [{"role": "user", "content": content}], **extra},
    )


# -- end to end ------------------------------------------------------------------------------


def test_upstream_never_sees_pii_and_client_gets_it_back():
    upstream = FakeUpstream()
    with client_for(apps_config(), upstream) as client:
        response = chat(client)
    assert response.status_code == 200
    sent = json.dumps(upstream.last_body)
    for secret in ["Rahul", "Sharma", "4111", "rahul@example.com"]:
        assert secret not in sent
    assert "SWIGGY" in sent and "450.00" in sent
    answer = response.json()["choices"][0]["message"]["content"]
    assert answer == "Summary: Rahul Sharma and 4111 1111 1111 1111 and rahul@example.com spent money at SWIGGY."
    assert response.headers["X-Hushmask-Masked"] == "3"
    assert response.headers["X-Hushmask-Unknown-Tokens"] == "0"


def test_provider_key_comes_from_proxy_not_app():
    upstream = FakeUpstream()
    with client_for(apps_config(), upstream) as client:
        chat(client)
    assert upstream.requests[-1].headers["authorization"] == "Bearer sk-real-provider-key"


def test_wrong_app_key_is_rejected_before_anything_is_sent():
    upstream = FakeUpstream()
    with client_for(apps_config(), upstream) as client:
        response = chat(client, key="nope")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
    assert upstream.requests == []


def test_passthrough_forwards_client_authorization():
    upstream = FakeUpstream()
    with client_for(passthrough_config("https://upstream.test/v1"), upstream) as client:
        response = chat(client, key="sk-client-own-key")
    assert response.status_code == 200
    assert upstream.requests[-1].headers["authorization"] == "Bearer sk-client-own-key"


def test_same_value_same_token_across_requests():
    upstream = FakeUpstream()
    with client_for(apps_config(), upstream) as client:
        chat(client, "card 4111 1111 1111 1111")
        first = upstream.last_body["messages"][-1]["content"]
        chat(client, "card 4111 1111 1111 1111")
        second = upstream.last_body["messages"][-1]["content"]
    assert first == second


def test_stream_request_gets_sse_with_restored_content():
    upstream = FakeUpstream()
    with client_for(apps_config(), upstream) as client:
        response = chat(client, stream=True, stream_options={"include_usage": True})
    assert response.headers["content-type"].startswith("text/event-stream")
    assert upstream.last_body["stream"] is False
    assert "stream_options" not in upstream.last_body
    events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    content = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
    assert "Rahul Sharma" in content


def test_images_refused_unless_allowed():
    upstream = FakeUpstream()
    message = [{"type": "text", "text": "what is this"}, {"type": "image_url", "image_url": {"url": "data:,"}}]
    with client_for(apps_config(), upstream) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer hm-spence"},
            json={"model": "m", "messages": [{"role": "user", "content": message}]},
        )
        stats = client.get("/hushmask/stats").json()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unmaskable_content"
    assert upstream.requests == []
    assert stats["spence"]["blocked_unmaskable"] == 1


def test_upstream_errors_pass_through():
    upstream = FakeUpstream(status=429)
    with client_for(apps_config(), upstream) as client:
        response = chat(client)
        stats = client.get("/hushmask/stats").json()
    assert response.status_code == 429
    assert stats["spence"]["upstream_errors"] == 1


def test_stats_hold_counts_not_values():
    upstream = FakeUpstream()
    with client_for(apps_config(), upstream) as client:
        chat(client)
        stats = client.get("/hushmask/stats").json()
    assert stats["spence"]["requests"] == 1
    assert stats["spence"]["masked"] == {"PERSON": 1, "CARD": 1, "EMAIL": 1}
    assert "Rahul" not in json.dumps(stats)


def test_models_passthrough():
    upstream = FakeUpstream()
    with client_for(apps_config(), upstream) as client:
        response = client.get("/v1/models", headers={"Authorization": "Bearer hm-spence"})
    assert response.json()["data"][0]["id"] == "fake-model"


def test_invented_tokens_are_reported():
    upstream = FakeUpstream(reply=lambda tokens: "PERSON_deadbe did it")
    with client_for(apps_config(), upstream) as client:
        response = chat(client)
    assert response.headers["X-Hushmask-Unknown-Tokens"] == "1"
    assert response.json()["choices"][0]["message"]["content"] == "PERSON_deadbe did it"


# -- request / response transforms -----------------------------------------------------------


def test_mask_request_covers_system_tool_and_name_fields():
    masker = Masker(known=[KnownValue("Rahul Sharma", EntityType.PERSON)])
    body = {
        "messages": [
            {"role": "system", "content": "User is Rahul Sharma."},
            {"role": "user", "name": "Rahul Sharma", "content": [{"type": "text", "text": "mail rahul@example.com"}]},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "1",
                        "type": "function",
                        "function": {"name": "f", "arguments": '{"to": "rahul@example.com"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "1", "content": "sent to rahul@example.com"},
        ]
    }
    masked, counts = mask_request(body, masker)
    assert "Rahul" not in json.dumps(masked) and "rahul@" not in json.dumps(masked)
    assert masked["messages"][0]["content"].endswith(PLACEHOLDER_NOTE)
    assert json.loads(masked["messages"][2]["tool_calls"][0]["function"]["arguments"])["to"].startswith("EMAIL_")
    assert counts["EMAIL"] == 3
    assert body["messages"][0]["content"] == "User is Rahul Sharma."  # original untouched


def test_system_messages_skip_model_detectors_but_keep_known_values():
    from hushmask import GlinerDetector
    from tests.test_ner import FakeModel

    model = FakeModel({"food delivery": "person", "anna weber": "person"})
    masker = Masker(known=[KnownValue("Rahul Sharma", EntityType.PERSON)], extra_detectors=[GlinerDetector(model)])
    body = {
        "messages": [
            {"role": "system", "content": "User is Rahul Sharma. Use Food delivery as a category."},
            {"role": "user", "content": "Food delivery paid to Anna Weber"},
        ]
    }
    masked, _ = mask_request(body, masker, placeholder_note=False)
    system, user = masked["messages"][0]["content"], masked["messages"][1]["content"]
    assert "Rahul" not in system and "Food delivery" in system
    assert "Anna" not in user


def test_note_added_as_system_message_when_none_exists():
    masked, _ = mask_request({"messages": [{"role": "user", "content": "mail x@example.com"}]}, Masker())
    assert masked["messages"][0] == {"role": "system", "content": PLACEHOLDER_NOTE}


def test_no_note_when_nothing_was_masked():
    masked, counts = mask_request({"messages": [{"role": "user", "content": "hello"}]}, Masker())
    assert len(masked["messages"]) == 1 and not counts


def test_unmaskable_parts_raise():
    body = {"messages": [{"role": "user", "content": [{"type": "input_audio", "input_audio": {}}]}]}
    with pytest.raises(UnmaskableContent):
        mask_request(body, Masker())
    mask_request(body, Masker(), allow_images=True)  # allowed: no error


def test_restore_json_content_survives_quotes_in_real_values():
    masker = Masker(known=[KnownValue('Flat 4 "Rose Villa"', EntityType.ADDRESS)])
    token = masker.mask('Flat 4 "Rose Villa"').tokens[0]
    response = {"choices": [{"message": {"role": "assistant", "content": json.dumps({"address": token})}}]}
    restored, unknown = restore_response(response, masker)
    assert json.loads(restored["choices"][0]["message"]["content"]) == {"address": 'Flat 4 "Rose Villa"'}
    assert not unknown


def test_restore_tool_call_arguments():
    masker = Masker()
    token = masker.mask("x@example.com").tokens[0]
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{"function": {"name": "send", "arguments": f'{{"to": "{token}"}}'}}],
                }
            }
        ]
    }
    restored, _ = restore_response(response, masker)
    assert json.loads(restored["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]) == {
        "to": "x@example.com"
    }


def test_sse_includes_tool_calls_and_usage():
    body = {
        "id": "c",
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "t", "function": {"name": "f"}}],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"total_tokens": 3},
    }
    events = list(to_sse(body))
    first = json.loads(events[0][6:])
    assert first["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert json.loads(events[1][6:])["choices"][0]["finish_reason"] == "tool_calls"
    assert json.loads(events[2][6:])["usage"] == {"total_tokens": 3}
    assert events[-1] == "data: [DONE]\n\n"


# -- config -----------------------------------------------------------------------------------


def test_load_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GEMINI_KEY", "g-123")
    path = tmp_path / "hushmask.toml"
    path.write_text(
        """
timeout = 30
[apps.spence]
key = "hm-1"
upstream_url = "https://example.test/v1/"
upstream_api_key_env = "TEST_GEMINI_KEY"
preset = "finance"
known = ["PERSON=Rahul Sharma"]
ner = true

[apps.notes]
key = "hm-2"
upstream_url = "http://localhost:11434/v1"
""",
        encoding="utf-8",
    )
    config = load_config(path)
    spence = config.apps["spence"]
    assert spence.upstream_url == "https://example.test/v1"
    assert spence.upstream_api_key == "g-123"
    assert spence.known == (KnownValue("Rahul Sharma", EntityType.PERSON),)
    assert config.uses_ner and config.timeout == 30
    assert config.apps["notes"].upstream_api_key is None


def test_example_config_loads(monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("GEMINI_API_KEY", "x")
    config = load_config(Path(__file__).parent.parent / "hushmask.example.toml")
    assert set(config.apps) == {"spence", "notes"}


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ("", "no [apps"),
        ('[apps.a]\nupstream_url = "u"', "key is required"),
        ('[apps.a]\nkey = "k"\nupstream_url = "u"\npreset = "loose"', "unknown preset"),
        ('[apps.a]\nkey = "k"\nupstream_url = "u"\n[apps.b]\nkey = "k"\nupstream_url = "u"', "used by another app"),
        ('[apps.a]\nkey = "k"\nupstream_url = "u"\nupstream_api_key_env = "HUSHMASK_MISSING_ENV"', "not set"),
    ],
)
def test_config_errors(tmp_path, toml, message):
    path = tmp_path / "c.toml"
    path.write_text(toml, encoding="utf-8")
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_config(path)
