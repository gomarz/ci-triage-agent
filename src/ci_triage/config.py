"""Runtime configuration, loaded from environment or a local .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings.

    Values come from the environment, falling back to a local .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_token: str = ""
    target_repo: str = ""
    #: Root of one corpus (raw/runs, raw/jobs, raw/logs). A second repo gets its own
    #: directory so its logs never mix into the counts recorded for the first.
    #: A relative DATA_DIR resolves from the working directory.
    data_dir: Path = PROJECT_ROOT / "data"
    aws_region: str = "us-west-2"
    log_level: str = "INFO"

    @property
    def repo_owner(self) -> str:
        return self.target_repo.split("/", 1)[0] if "/" in self.target_repo else ""

    @property
    def repo_name(self) -> str:
        return self.target_repo.split("/", 1)[1] if "/" in self.target_repo else ""


def load_settings() -> Settings:
    """Build a Settings instance. Separate from the class so tests can patch it."""
    return Settings()
