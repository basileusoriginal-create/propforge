"""Erste Stufe: aus einem Prompt ein Mesh machen.

Bis hierher kam das Modell von Hand - aus Fab, aus Meshy, per Download. Diese
Stufe schliesst die Luecke davor: Prompt rein, GLB raus, direkt weiter in
`ingest`.

Warum Tripo als erster Anbieter:

  - **Pay-as-you-go ohne Abo.** 1 Credit = 1 US-Cent, Text-zu-3D mit Textur
    20 Credits. Kein Monatsplan noetig, um an die API zu kommen.
  - **Kommerzielle Rechte haengen an der API-Nutzung**, ohne Namensnennung.
    Bei Meshy braucht es dafuer den Pro-Plan; die kostenlose Stufe steht
    unter CC BY, verlangt also Attribution im Endprodukt.
  - **Liefert GLB mit PBR-Texturen** und kennt eine Dreiecksobergrenze -
    genau das, was die Pipeline danach braucht.

Selbst hosten waere die Alternative ohne laufende Kosten, hat aber zwei
Haken: Hunyuan3D (das beste offene PBR-Modell) schliesst die Europaeische
Union in seiner Lizenz ausdruecklich aus, und TRELLIS.2 (MIT, also frei
nutzbar) kann nur Bild-zu-3D und will 24 GB VRAM. Beides ist im Zweifel
nachruestbar: die Anbieterschnittstelle unten ist bewusst schmal.

Der HTTP-Zugriff ist injizierbar. Diese Stufe laesst sich hier nicht gegen
den echten Dienst ausprobieren - also wird die gesamte Ablauflogik gegen
einen Ersatz getestet, statt sie beim ersten Aufruf zu erraten.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

TRIPO_BASE = "https://openapi.tripo3d.ai/v3"

# Die Modellversion ist PFLICHT - das hat der erste echte Aufruf gezeigt:
#
#   HTTP 400 {"code":1004,"message":"model is required, allowed values:
#             P1-20260311, P2-20260801, v2.5-20250123, v3.0-20250812,
#             v3.1-20260211"}
#
# Ich hatte das Feld weggelassen, damit keine Konstante still veraltet. Der
# Dienst sieht das anders. Immerhin nennt er die gueltigen Werte selbst -
# genau das faengt `explain_api_error` unten ab und reicht es weiter.
#
# P1 als Vorgabe, nicht P2: P1 ist schneller und billiger, und fuer
# Hintergrund- und Einrichtungs-Props reicht die Qualitaet. P2 bringt
# sauberere Texturen im Nahbereich und Quad-Topologie - dafuer teurer.
# Umschalten mit --model.
DEFAULT_MODEL = "P1-20260311"
BETTER_MODEL = "P2-20260801"

# Die Ergebnis-URL laeuft laut Tripo nach fuenf Minuten ab. Nach dem Abschluss
# wird deshalb sofort geladen, nicht spaeter.
URL_LIFETIME_SECONDS = 300

GLB_MAGIC = b"glTF"


def load_env_file(path: Path) -> dict[str, str]:
    """Liest eine schlichte KEY=VALUE-Datei.

    Damit der Schluessel an einer Stelle liegen kann, ohne ihn bei jedem
    Terminal neu zu setzen. Die Datei steht in der .gitignore: das Repo ist
    oeffentlich, ein eingecheckter Schluessel waere sofort fuer alle sichtbar.

    Bewusst ohne Zusatzbibliothek und ohne Kunststuecke - keine
    Variablenersetzung, keine Mehrzeiligkeit. Wer mehr braucht, nimmt
    Umgebungsvariablen.
    """
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def find_token(explicit: str | None = None, env_file: Path | None = None) -> str | None:
    """Schluessel suchen: Aufrufparameter, dann Umgebung, dann .env-Datei."""
    import os

    if explicit:
        return explicit
    from_env = os.environ.get("TRIPO_API_KEY")
    if from_env:
        return from_env

    path = env_file or Path(__file__).resolve().parent.parent / ".env"
    return load_env_file(path).get("TRIPO_API_KEY")


class GenerationError(RuntimeError):
    """Der Generator hat kein brauchbares Ergebnis geliefert."""


@dataclass
class GenerationRequest:
    prompt: str
    name: str
    # Dreiecksobergrenze schon beim Generator statt spaeter per Decimate.
    # Der Generator kennt die Form und kann besser entscheiden, wo Kanten
    # wegfallen duerfen, als ein blinder Reduktionsalgorithmus.
    face_limit: int | None = None
    pbr: bool = True
    texture: bool = True
    texture_quality: str = "detailed"
    model_version: str | None = None
    image: Path | None = None

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": self.prompt,
            # Pflichtfeld. Ohne Modellversion lehnt Tripo den Auftrag ab.
            "model": self.model_version or DEFAULT_MODEL,
            "texture": self.texture,
            "pbr": self.pbr,
            "texture_quality": self.texture_quality,
        }
        if self.face_limit:
            body["face_limit"] = int(self.face_limit)
        return body


@dataclass
class TaskState:
    status: str
    progress: int = 0
    model_url: str | None = None
    message: str = ""

    @property
    def finished(self) -> bool:
        return self.status in {"success", "failed", "cancelled", "banned", "expired"}

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


def explain_api_error(status: int, detail: str) -> str:
    """Macht aus der Antwort des Dienstes eine brauchbare Meldung.

    Tripo schickt bei Fehlern ein JSON mit `message` und oft `suggestion` -
    und nennt bei ungueltigen Aufzaehlungswerten die gueltigen gleich mit.
    Das ist mehr wert als der rohe Rumpf: wenn eine Modellversion eines Tages
    zurueckgezogen wird, steht die Antwort auf "was jetzt?" in der
    Fehlermeldung selbst.
    """
    try:
        body = json.loads(detail)
    except (ValueError, TypeError):
        return f"HTTP {status}: {detail}"

    message = body.get("message") or body.get("msg") or detail
    lines = [f"HTTP {status}: {message}"]

    if "allowed values" in str(message):
        _, _, allowed = str(message).partition("allowed values:")
        values = [v.strip() for v in allowed.split(",") if v.strip()]
        if values:
            lines.append("Moegliche Werte laut Dienst: " + ", ".join(values))
            lines.append(f"Mit --model setzen, z.B. --model {values[0]}")

    suggestion = body.get("suggestion")
    if suggestion:
        lines.append(str(suggestion))
    if body.get("request_id"):
        lines.append(f"request_id: {body['request_id']}")
    return "\n  ".join(lines)


def http_json(
    url: str,
    *,
    token: str,
    method: str = "GET",
    body: dict | None = None,
    timeout: float = 60.0,
) -> dict:
    """Ein JSON-Aufruf. Ausgelagert, damit Tests ihn ersetzen koennen."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise GenerationError(explain_api_error(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise GenerationError(f"{method} {url} nicht erreichbar: {exc.reason}") from exc


def http_download(url: str, target: Path, timeout: float = 300.0) -> Path:
    """Laedt die Ergebnisdatei. Ohne Token - die URL traegt ihre Freigabe selbst."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            target.write_bytes(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise GenerationError(f"Download von {url} fehlgeschlagen: {exc}") from exc
    return target


def check_glb(path: Path) -> None:
    """Prueft, dass wirklich ein GLB angekommen ist.

    Eine abgelaufene oder umgeleitete URL liefert gern eine Fehlerseite mit
    Status 200. Die laege dann als '.glb' auf der Platte und scheiterte erst
    drei Stufen spaeter mit einer unverstaendlichen Meldung.
    """
    size = path.stat().st_size if path.is_file() else 0
    if size == 0:
        raise GenerationError(f"{path.name} ist leer - der Download hat nichts geliefert.")

    head = path.read_bytes()[:4]
    if head != GLB_MAGIC:
        raise GenerationError(
            f"{path.name} beginnt nicht mit '{GLB_MAGIC.decode()}', sondern mit "
            f"{head!r}. Das ist kein GLB - vermutlich eine Fehlerseite. "
            "Ergebnis-URLs von Tripo laufen nach fuenf Minuten ab."
        )


@dataclass
class TripoProvider:
    """Zugriff auf die Tripo-OpenAPI.

    Die drei HTTP-Funktionen sind Felder, keine Aufrufe im Rumpf: so laesst
    sich der ganze Ablauf ohne Netz pruefen.
    """

    token: str
    base_url: str = TRIPO_BASE
    call: Callable[..., dict] = http_json
    download: Callable[[str, Path], Path] = http_download
    sleep: Callable[[float], None] = time.sleep

    name = "tripo"

    def _data(self, response: dict, what: str) -> dict:
        # Tripo meldet Fehler im Rumpf, nicht im HTTP-Status. Ein 200 mit
        # code != 0 ist ein Fehlschlag - wer nur den Status prueft, haelt ihn
        # fuer Erfolg.
        code = response.get("code")
        if code not in (0, None):
            message = response.get("message") or response.get("msg") or "ohne Meldung"
            raise GenerationError(f"Tripo lehnte {what} ab (code {code}): {message}")
        data = response.get("data")
        if not isinstance(data, dict):
            raise GenerationError(f"Antwort auf {what} enthaelt kein 'data': {response}")
        return data

    def create(self, request: GenerationRequest) -> str:
        endpoint = f"{self.base_url}/generation/text-to-model"
        data = self._data(
            self.call(endpoint, token=self.token, method="POST", body=request.payload()),
            "die Auftragserstellung",
        )
        task_id = data.get("task_id")
        if not task_id:
            raise GenerationError(f"Keine task_id in der Antwort: {data}")
        return str(task_id)

    def state(self, task_id: str) -> TaskState:
        endpoint = f"{self.base_url}/tasks/{task_id}"
        data = self._data(self.call(endpoint, token=self.token), f"die Abfrage von {task_id}")
        output = data.get("output") or {}
        return TaskState(
            status=str(data.get("status", "unknown")),
            progress=int(data.get("progress") or 0),
            model_url=output.get("model_url") or output.get("pbr_model") or output.get("model"),
            message=str(data.get("message") or ""),
        )

    def wait(
        self,
        task_id: str,
        *,
        timeout: float = 900.0,
        interval: float = 5.0,
        on_progress: Callable[[TaskState], None] | None = None,
    ) -> TaskState:
        deadline = time.monotonic() + timeout
        last_progress = -1

        while True:
            state = self.state(task_id)
            if on_progress and state.progress != last_progress:
                on_progress(state)
                last_progress = state.progress

            if state.finished:
                if not state.succeeded:
                    raise GenerationError(
                        f"Auftrag {task_id} endete als '{state.status}'"
                        + (f": {state.message}" if state.message else "")
                    )
                if not state.model_url:
                    raise GenerationError(
                        f"Auftrag {task_id} meldet Erfolg, liefert aber keine model_url. "
                        "Ohne Datei ist der Erfolg wertlos."
                    )
                return state

            if time.monotonic() >= deadline:
                raise GenerationError(
                    f"Auftrag {task_id} war nach {timeout:.0f} s nicht fertig "
                    f"(Status '{state.status}', {state.progress} %). "
                    "Der Auftrag laeuft bei Tripo weiter - mit 'propforge fetch "
                    f"{task_id}' spaeter abholen."
                )

            self.sleep(interval)

    def run(self, request: GenerationRequest, target: Path, **wait_args) -> Path:
        task_id = self.create(request)
        state = self.wait(task_id, **wait_args)
        # Sofort laden: die URL laeuft nach fuenf Minuten ab.
        self.download(state.model_url, target)
        check_glb(target)
        return target


PROVIDERS: dict[str, type] = {"tripo": TripoProvider}


def describe_request(request: GenerationRequest, provider: str = "tripo") -> str:
    """Was abgeschickt wuerde - fuer den Trockenlauf."""
    endpoint = f"{TRIPO_BASE}/generation/text-to-model"
    return (
        f"POST {endpoint}\n"
        f"Authorization: Bearer <{provider.upper()}_API_KEY>\n"
        f"Content-Type: application/json\n\n"
        + json.dumps(request.payload(), indent=2, ensure_ascii=False)
    )
