import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from update_checker import check_for_updates, fetch_update_manifest, is_newer_version  # noqa: E402


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.payload


def opener_for(value):
    payload = json.dumps(value).encode("utf-8")

    def open_url(_request, timeout=0):
        assert timeout > 0
        return Response(payload)

    return open_url


def manifest(version="2.1.11"):
    return {
        "schema_version": 1,
        "app_version": version,
        "bridge_version": "1.4.15",
        "release_url": (
            "https://github.com/XiaoLan9999/maimai-vrchat-osc/releases/tag/v{0}"
        ).format(version),
    }


def main():
    assert is_newer_version("2.1.11", "2.1.10")
    assert is_newer_version("2.2", "2.1.99")
    assert not is_newer_version("2.1.11", "2.1.11.0")

    available = check_for_updates("2.1.10", opener=opener_for(manifest()))
    assert available["state"] == "update", available
    current = check_for_updates("2.1.11", opener=opener_for(manifest()))
    assert current["state"] == "current", current

    invalid = manifest()
    invalid["release_url"] = "https://example.com/download"
    try:
        fetch_update_manifest(opener=opener_for(invalid))
    except ValueError:
        pass
    else:
        raise AssertionError("non-GitHub release URL was accepted")

    invalid = manifest("version-latest")
    try:
        fetch_update_manifest(opener=opener_for(invalid))
    except ValueError:
        pass
    else:
        raise AssertionError("invalid version was accepted")

    print("update checker ok: comparison, manifest validation, trusted release URL")


if __name__ == "__main__":
    main()
