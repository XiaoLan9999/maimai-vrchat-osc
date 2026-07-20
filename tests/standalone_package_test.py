import json
import pathlib
import sys
import zipfile


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: standalone_package_test.py <zip>")
    archive = pathlib.Path(sys.argv[1])
    with zipfile.ZipFile(archive) as bundle:
        names = {name.replace("\\", "/") for name in bundle.namelist()}
        required = {
            "MaimaiVrchatOsc.exe",
            "README.md",
            "README.zh-CN.md",
            "LICENSE",
            "config.example.json",
        }
        assert required <= names, sorted(required - names)
        assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
        exe = bundle.read("MaimaiVrchatOsc.exe")
        assert exe[:2] == b"MZ"
        config = json.loads(bundle.read("config.example.json").decode("utf-8"))
        assert config["endpoint"] == "http://127.0.0.1:8891/events"
        assert config["osc_keepalive_interval"] == 5.0
    assert archive.stat().st_size < 80 * 1024 * 1024
    print("standalone package ok: executable, docs, config, safe paths")


if __name__ == "__main__":
    main()
