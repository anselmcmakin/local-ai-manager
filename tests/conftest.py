import importlib, json, os, pathlib, sys
import pytest
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "localai"
sys.path.insert(0, str(SRC))

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "LocalAI").mkdir()
    return tmp_path

def load(name):
    if name in sys.modules: del sys.modules[name]
    return importlib.import_module(name)
