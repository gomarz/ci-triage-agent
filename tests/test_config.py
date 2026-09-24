from pathlib import Path

from ci_triage.config import PROJECT_ROOT, Settings


def test_repo_parts_split_owner_and_name():
    settings = Settings(target_repo="gomarz/SS-armaa")
    assert settings.repo_owner == "gomarz"
    assert settings.repo_name == "SS-armaa"


def test_repo_parts_empty_when_unset():
    settings = Settings(target_repo="")
    assert settings.repo_owner == ""
    assert settings.repo_name == ""


def test_defaults():
    settings = Settings()
    assert settings.aws_region
    assert settings.log_level in {"DEBUG", "INFO", "WARNING", "ERROR"}


def test_data_dir_defaults_to_project_data(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    assert Settings(_env_file=None).data_dir == PROJECT_ROOT / "data"


def test_data_dir_comes_from_environment(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "data/testbed")
    assert Settings(_env_file=None).data_dir == Path("data/testbed")
