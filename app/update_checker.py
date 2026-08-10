"""Small, dependency-free application update checker."""

import json
import re
import urllib.parse
import urllib.request


UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/XiaoLan9999/"
    "maimai-vrchat-osc/main/latest.json"
)
RELEASE_PATH_PREFIX = "/XiaoLan9999/maimai-vrchat-osc/"
MAX_MANIFEST_BYTES = 64 * 1024
_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")


def version_tuple(value):
    text = str(value or "").strip()
    if not _VERSION_PATTERN.fullmatch(text):
        raise ValueError("invalid version: {0}".format(text))
    parts = tuple(int(part) for part in text.split("."))
    return parts + (0,) * (4 - len(parts))


def is_newer_version(candidate, current):
    return version_tuple(candidate) > version_tuple(current)


def _validated_release_url(value):
    text = str(value or "").strip()
    parsed = urllib.parse.urlparse(text)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or not parsed.path.startswith(RELEASE_PATH_PREFIX)
    ):
        raise ValueError("invalid release URL")
    return text


def fetch_update_manifest(url=UPDATE_MANIFEST_URL, timeout=4.0, opener=None):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MaimaiVrchatOsc-UpdateChecker"},
    )
    open_url = opener or urllib.request.urlopen
    with open_url(request, timeout=timeout) as response:
        payload = response.read(MAX_MANIFEST_BYTES + 1)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("update manifest is too large")
    manifest = json.loads(payload.decode("utf-8-sig"))
    if int(manifest.get("schema_version", 0)) != 1:
        raise ValueError("unsupported update manifest")
    app_version = str(manifest.get("app_version", "")).strip()
    bridge_version = str(manifest.get("bridge_version", "")).strip()
    version_tuple(app_version)
    version_tuple(bridge_version)
    return {
        "app_version": app_version,
        "bridge_version": bridge_version,
        "release_url": _validated_release_url(manifest.get("release_url")),
    }


def check_for_updates(current_version, url=UPDATE_MANIFEST_URL, timeout=4.0, opener=None):
    manifest = fetch_update_manifest(url, timeout, opener)
    latest = manifest["app_version"]
    return {
        "state": "update" if is_newer_version(latest, current_version) else "current",
        "current_version": str(current_version),
        "latest_version": latest,
        "bridge_version": manifest["bridge_version"],
        "release_url": manifest["release_url"],
    }
