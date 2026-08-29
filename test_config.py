from ci_triage.config import Settings


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
