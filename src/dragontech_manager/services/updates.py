"""Consulta de metadatos de releases, sin descargar ni ejecutar artefactos."""

from dataclasses import dataclass
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

UPDATE_MANIFEST_URL: str | None = None
_TIMEOUT_SECONDS = 4
_MAX_RESPONSE_BYTES = 64 * 1024
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class UpdateCheckResult:
    status: str
    message: str
    latest_version: str | None = None
    release_url: str | None = None
    artifact_sha256: str | None = None
    signature: str | None = None


class UpdateChecker:
    """Lee un manifiesto HTTPS configurado; no instala ni verifica firmas aún."""

    def __init__(self, manifest_url: str | None = None, opener=None) -> None:
        self.manifest_url = UPDATE_MANIFEST_URL if manifest_url is None else manifest_url
        self.opener = opener or urlopen

    @property
    def is_configured(self) -> bool:
        return bool(self.manifest_url)

    def check(self, current_version: str) -> UpdateCheckResult:
        if not self.manifest_url:
            return UpdateCheckResult(
                "not_configured",
                "El canal oficial de actualizaciones aún no está configurado.",
            )
        manifest = urlparse(self.manifest_url)
        if manifest.scheme != "https" or not manifest.hostname or manifest.username or manifest.password:
            return UpdateCheckResult("error", "La URL del canal debe ser HTTPS y no contener credenciales.")

        try:
            request = Request(self.manifest_url, headers={"Accept": "application/json"})
            with self.opener(request, timeout=_TIMEOUT_SECONDS) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                return UpdateCheckResult("error", "El manifiesto de versiones supera el tamaño permitido.")
            payload = json.loads(body.decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError):
            return UpdateCheckResult("offline", "No fue posible conectar con el canal de actualizaciones.")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return UpdateCheckResult("error", "El canal devolvió un manifiesto inválido.")

        if not isinstance(payload, dict):
            return UpdateCheckResult("error", "El manifiesto de versiones no tiene el formato esperado.")
        version = payload.get("version")
        release_url = payload.get("release_url")
        checksum = payload.get("artifact_sha256")
        signature = payload.get("signature")
        current_match = _VERSION_RE.fullmatch(current_version)
        latest_match = _VERSION_RE.fullmatch(version) if isinstance(version, str) else None
        release = urlparse(release_url) if isinstance(release_url, str) else None
        if (
            current_match is None
            or latest_match is None
            or release is None
            or release.scheme != "https"
            or release.hostname != manifest.hostname
            or not isinstance(checksum, str)
            or not _SHA256_RE.fullmatch(checksum)
            or not isinstance(signature, str)
            or not signature.strip()
        ):
            return UpdateCheckResult(
                "error",
                "El manifiesto no contiene versión, enlace HTTPS del mismo canal, SHA-256 y firma requeridos.",
            )

        latest_key = tuple(int(part) for part in latest_match.groups())
        current_key = tuple(int(part) for part in current_match.groups())
        if latest_key <= current_key:
            return UpdateCheckResult("current", "DragonTech Manager está al día.", version)
        return UpdateCheckResult(
            "available",
            f"Hay una versión publicada: {version}. La aplicación no descarga ni instala actualizaciones.",
            version,
            release_url,
            checksum.lower(),
            signature,
        )
