"""Tests fuer die Generierungsstufe.

Diese Stufe laesst sich hier nicht gegen den echten Dienst ausprobieren - es
gibt keinen Schluessel und kein Netz. Genau deshalb wird der komplette Ablauf
gegen einen Ersatz geprueft: Auftrag anlegen, warten, Zustaende deuten,
herunterladen, Ergebnis kontrollieren.

Die Faelle sind nicht ausgedacht, sondern die dokumentierten Eigenheiten der
Tripo-API: Fehler stehen im Rumpf statt im HTTP-Status, und Ergebnis-URLs
laufen nach fuenf Minuten ab.
"""

from pathlib import Path

import pytest

from propforge import generate as gen


class FakeApi:
    """Ersetzt den HTTP-Zugriff und protokolliert, was gefragt wurde."""

    def __init__(self, states, create=None, task_id="task_abc123"):
        self.states = list(states)
        self.create_response = create or {"code": 0, "data": {"task_id": task_id}}
        self.calls: list[tuple[str, str, dict | None]] = []
        self.downloads: list[str] = []
        self.slept: list[float] = []
        self.payload = b"glTF\x02\x00\x00\x00rest"

    def call(self, url, *, token, method="GET", body=None, timeout=60.0):
        self.calls.append((method, url, body))
        if method == "POST":
            return self.create_response
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def download(self, url, target):
        self.downloads.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.payload)
        return target

    def sleep(self, seconds):
        self.slept.append(seconds)


def state(status="success", progress=100, url="https://cdn.example/model.glb", **extra):
    data = {"status": status, "progress": progress, **extra}
    if url is not None:
        data["output"] = {"model_url": url}
    return {"code": 0, "data": data}


def provider(api, **kwargs):
    return gen.TripoProvider(
        token="t", call=api.call, download=api.download, sleep=api.sleep, **kwargs)


def request(**kwargs):
    base = dict(prompt="ein Holztisch", name="pf_tisch")
    base.update(kwargs)
    return gen.GenerationRequest(**base)


class TestTokenLookup:
    """Der Schluessel darf nicht im oeffentlichen Repo landen - deshalb .env
    (in der .gitignore) statt einer Zeile in der Konfiguration."""

    def test_explicit_wins(self, tmp_path):
        assert gen.find_token("direkt", env_file=tmp_path / "fehlt") == "direkt"

    def test_reads_env_file(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("TRIPO_API_KEY=tsk_aus_datei\n")
        assert gen.find_token(None, env_file=path) == "tsk_aus_datei"

    def test_missing_file_is_not_an_error(self, tmp_path):
        assert gen.load_env_file(tmp_path / "gibtsnicht") == {}

    def test_ignores_comments_and_blanks(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("# Kommentar\n\nTRIPO_API_KEY=abc\nkaputte Zeile\n")
        assert gen.load_env_file(path) == {"TRIPO_API_KEY": "abc"}

    def test_strips_quotes_and_spaces(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text('TRIPO_API_KEY = "tsk_123"  \n')
        assert gen.load_env_file(path)["TRIPO_API_KEY"] == "tsk_123"

    def test_none_when_nowhere(self, tmp_path, monkeypatch=None):
        import os

        saved = os.environ.pop("TRIPO_API_KEY", None)
        try:
            assert gen.find_token(None, env_file=tmp_path / "fehlt") is None
        finally:
            if saved is not None:
                os.environ["TRIPO_API_KEY"] = saved


class TestProfilePassThrough:
    """Die ausdrueckliche Wahl darf die Schaetzung nicht verlieren."""

    def test_explicit_profile_beats_estimate(self):
        from propforge.ingest import AssetInfo, config_snippet, suggest_profile

        info = AssetInfo(name="pf_flasche", triangles=2400, vertices=1200,
                         dimensions=(0.07, 0.07, 0.25), center=(0, 0, 0),
                         has_uvs=True, materials=1, double_sided=False, textures={})
        # Die Schaetzung allein saehe hier 'standard'.
        assert suggest_profile(2400) == "standard"
        snippet = config_snippet(info, Path("a/pf.glb"), Path("a"), None, "clutter")
        assert 'profile = "clutter"' in snippet

    def test_estimate_used_when_nothing_chosen(self):
        from propforge.ingest import AssetInfo, config_snippet

        info = AssetInfo(name="pf_x", triangles=800, vertices=400,
                         dimensions=(1, 1, 1), center=(0, 0, 0),
                         has_uvs=True, materials=1, double_sided=False, textures={})
        assert 'profile = "clutter"' in config_snippet(
            info, Path("a/pf.glb"), Path("a"), None, None)


class TestPayload:
    def test_asks_for_pbr_and_texture(self):
        body = request().payload()
        assert body["pbr"] is True
        assert body["texture"] is True

    def test_face_limit_only_when_set(self):
        assert "face_limit" not in request().payload()
        assert request(face_limit=6000).payload()["face_limit"] == 6000

    def test_zero_face_limit_is_omitted(self):
        assert "face_limit" not in request(face_limit=0).payload()

    def test_model_is_always_sent(self):
        # Pflichtfeld. Der erste echte Aufruf scheiterte an genau dieser
        # Annahme: HTTP 400 "model is required".
        assert request().payload()["model"] == gen.DEFAULT_MODEL

    def test_model_can_be_overridden(self):
        assert request(model_version=gen.BETTER_MODEL).payload()["model"] == gen.BETTER_MODEL

    def test_dry_run_shows_endpoint_and_body(self):
        text = gen.describe_request(request(face_limit=6000))
        assert "openapi.tripo3d.ai/v3/generation/text-to-model" in text
        assert '"face_limit": 6000' in text
        assert "Bearer" in text


class TestApiErrors:
    """Die Antwort des Dienstes ist oft hilfreicher als alles, was wir raten
    koennten - sie muss nur lesbar durchgereicht werden."""

    ALLOWED = (
        '{"code":1004,"status":"error","message":"model is required, allowed '
        'values: P1-20260311, P2-20260801, v2.5-20250123",ّ"suggestion":"Refer to '
        'the API documentation","request_id":"abc"}'
    ).replace("ّ", "")

    def test_message_is_extracted(self):
        text = gen.explain_api_error(400, self.ALLOWED)
        assert "model is required" in text

    def test_allowed_values_are_listed(self):
        text = gen.explain_api_error(400, self.ALLOWED)
        assert "P1-20260311" in text and "P2-20260801" in text

    def test_names_the_flag_to_use(self):
        # Ohne diesen Hinweis muss man in der Doku suchen, obwohl der Dienst
        # die Antwort schon mitgeliefert hat.
        assert "--model" in gen.explain_api_error(400, self.ALLOWED)

    def test_suggestion_and_request_id_kept(self):
        text = gen.explain_api_error(400, self.ALLOWED)
        assert "API documentation" in text
        assert "request_id: abc" in text

    def test_non_json_body_is_passed_through(self):
        assert "Bad Gateway" in gen.explain_api_error(502, "Bad Gateway")

    def test_plain_error_without_allowed_values(self):
        text = gen.explain_api_error(402, '{"code":2002,"message":"insufficient credits"}')
        assert "insufficient credits" in text
        assert "--model" not in text


class TestCreate:
    def test_returns_task_id(self):
        api = FakeApi([state()])
        assert provider(api).create(request()) == "task_abc123"
        method, url, body = api.calls[0]
        assert method == "POST"
        assert url.endswith("/generation/text-to-model")
        assert body["prompt"] == "ein Holztisch"

    def test_error_in_body_is_not_success(self):
        # Tripo meldet Fehler mit HTTP 200 und code != 0. Wer nur den Status
        # prueft, haelt das fuer Erfolg.
        api = FakeApi([], create={"code": 2002, "message": "insufficient credits"})
        with pytest.raises(gen.GenerationError, match="insufficient credits"):
            provider(api).create(request())

    def test_missing_task_id_is_an_error(self):
        api = FakeApi([], create={"code": 0, "data": {}})
        with pytest.raises(gen.GenerationError, match="task_id"):
            provider(api).create(request())

    def test_missing_data_is_an_error(self):
        api = FakeApi([], create={"code": 0})
        with pytest.raises(gen.GenerationError, match="data"):
            provider(api).create(request())


class TestWait:
    def test_polls_until_finished(self):
        api = FakeApi([
            state("queued", 0, url=None),
            state("running", 40, url=None),
            state("success", 100),
        ])
        result = provider(api).wait("t1", interval=0.0)
        assert result.succeeded
        assert result.model_url == "https://cdn.example/model.glb"
        assert len(api.slept) == 2

    def test_failure_is_raised_with_status(self):
        api = FakeApi([state("failed", 60, url=None, message="prompt rejected")])
        with pytest.raises(gen.GenerationError, match="failed.*prompt rejected"):
            provider(api).wait("t1", interval=0.0)

    def test_cancelled_is_a_failure(self):
        api = FakeApi([state("cancelled", 10, url=None)])
        with pytest.raises(gen.GenerationError, match="cancelled"):
            provider(api).wait("t1", interval=0.0)

    def test_success_without_url_is_a_failure(self):
        # "Erfolg" ohne Datei ist kein Erfolg - genau die Sorte Meldung, die
        # diese Pipeline sonst durchwinkt.
        api = FakeApi([state("success", 100, url=None)])
        with pytest.raises(gen.GenerationError, match="model_url"):
            provider(api).wait("t1", interval=0.0)

    def test_timeout_mentions_the_task_id(self):
        api = FakeApi([state("running", 20, url=None)])
        with pytest.raises(gen.GenerationError, match="t1"):
            provider(api).wait("t1", interval=0.0, timeout=-1.0)

    def test_progress_reported_once_per_change(self):
        api = FakeApi([
            state("running", 10, url=None),
            state("running", 10, url=None),
            state("success", 100),
        ])
        seen = []
        provider(api).wait("t1", interval=0.0, on_progress=lambda s: seen.append(s.progress))
        assert seen == [10, 100]

    def test_alternative_output_keys_accepted(self):
        api = FakeApi([{"code": 0, "data": {
            "status": "success", "progress": 100,
            "output": {"pbr_model": "https://cdn.example/pbr.glb"}}}])
        assert provider(api).wait("t1", interval=0.0).model_url.endswith("pbr.glb")


class TestRun:
    def test_downloads_after_success(self, tmp_path):
        api = FakeApi([state()])
        target = tmp_path / "out" / "pf_tisch_raw.glb"
        provider(api).run(request(), target, interval=0.0)
        assert target.is_file()
        assert api.downloads == ["https://cdn.example/model.glb"]

    def test_rejects_non_glb_payload(self, tmp_path):
        # Eine abgelaufene URL liefert gern eine Fehlerseite mit Status 200.
        # Die laege sonst als .glb auf der Platte und scheiterte erst drei
        # Stufen spaeter mit einer unverstaendlichen Meldung.
        api = FakeApi([state()])
        api.payload = b"<!DOCTYPE html><html>Link expired</html>"
        with pytest.raises(gen.GenerationError, match="kein GLB"):
            provider(api).run(request(), tmp_path / "x.glb", interval=0.0)

    def test_rejects_empty_download(self, tmp_path):
        api = FakeApi([state()])
        api.payload = b""
        with pytest.raises(gen.GenerationError, match="leer"):
            provider(api).run(request(), tmp_path / "x.glb", interval=0.0)

    def test_expiry_hint_in_message(self, tmp_path):
        api = FakeApi([state()])
        api.payload = b"nope"
        with pytest.raises(gen.GenerationError, match="fuenf Minuten"):
            provider(api).run(request(), tmp_path / "x.glb", interval=0.0)


class TestCheckGlb:
    def test_accepts_real_header(self, tmp_path):
        path = tmp_path / "ok.glb"
        path.write_bytes(b"glTF\x02\x00\x00\x00")
        gen.check_glb(path)

    def test_missing_file_counts_as_empty(self, tmp_path):
        with pytest.raises(gen.GenerationError, match="leer"):
            gen.check_glb(tmp_path / "fehlt.glb")
