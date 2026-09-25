import os
import tomllib
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class ConfigError(ValueError):
    """Raised when askyourdb configuration is missing or invalid."""


DIALECTS_BY_BACKEND = {
    "postgresql": "PostgreSQL",
    "sqlite": "SQLite",
    "mysql": "MySQL",
}

ENV_PREFIX = "ASKYOURDB_"

# from_env key -> path inside the AnalystConfig data. The env var is
# ENV_PREFIX + key.upper().
ENV_FIELDS = {
    "dsn": ("database", "dsn"),
    "dialect": ("database", "dialect"),
    "model": ("models", "generator", "model"),
    "api_key": ("models", "generator", "api_key"),
    "semantic_model": ("models", "semantic_validator", "model"),
    "semantic_api_key": ("models", "semantic_validator", "api_key"),
    "summary_model": ("models", "summarizer", "model"),
    "summary_api_key": ("models", "summarizer", "api_key"),
}
ENV_VAR_BY_FIELD = {
    ".".join(path): ENV_PREFIX + key.upper() for key, path in ENV_FIELDS.items()
}


class _Model(BaseModel):
    # Never echo raw input (DSNs, keys) back in validation errors.
    model_config = ConfigDict(hide_input_in_errors=True)


class LLMConfig(_Model):
    model: str
    api_key: SecretStr | None = None
    temperature: float = 0.0

    @field_validator("model")
    @classmethod
    def _require_provider_prefix(cls, value: str) -> str:
        provider, separator, name = value.partition(":")
        if not (separator and provider.strip() and name.strip()):
            raise ValueError(
                "must be 'provider:model', e.g. 'anthropic:claude-sonnet-5'"
            )
        return value

    @property
    def provider(self) -> str:
        return self.model.partition(":")[0]


class ModelsConfig(_Model):
    generator: LLMConfig
    semantic_validator: LLMConfig | None = None
    summarizer: LLMConfig | None = None

    @property
    def resolved_semantic_validator(self) -> LLMConfig:
        return self.semantic_validator or self.generator

    @property
    def resolved_summarizer(self) -> LLMConfig:
        return self.summarizer or self.generator


class DatabaseConfig(_Model):
    dsn: SecretStr
    dialect: str | None = None

    @model_validator(mode="after")
    def _infer_dialect(self) -> "DatabaseConfig":
        if self.dialect and self.dialect.strip():
            return self
        try:
            backend = make_url(self.dsn.get_secret_value()).get_backend_name()
        except ArgumentError:
            # ArgumentError's message contains the DSN, so don't chain it.
            raise ValueError("database.dsn is not a valid SQLAlchemy URL") from None
        dialect = DIALECTS_BY_BACKEND.get(backend)
        if dialect is None:
            raise ValueError(
                f"cannot infer the SQL dialect for database backend '{backend}'; "
                f"set database.dialect (env {ENV_PREFIX}DIALECT)"
            )
        self.dialect = dialect
        return self


class AnalystConfig(_Model):
    database: DatabaseConfig
    models: ModelsConfig

    @classmethod
    def from_toml(cls, path: str | Path) -> "AnalystConfig":
        path = Path(path)
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except FileNotFoundError:
            raise ConfigError(f"Config file not found: {path}") from None
        except tomllib.TOMLDecodeError as error:
            raise ConfigError(f"Config file {path} is not valid TOML: {error}") from None
        return cls._validate(data, source=str(path))

    @classmethod
    def from_env(cls, **overrides: str | None) -> "AnalystConfig":
        unknown = set(overrides) - ENV_FIELDS.keys()
        if unknown:
            raise ConfigError(
                f"Unknown from_env override(s): {', '.join(sorted(unknown))}"
            )

        values = {}
        for key in ENV_FIELDS:
            value = os.environ.get(ENV_PREFIX + key.upper(), "").strip()
            if value:
                values[key] = value
        values.update({key: value for key, value in overrides.items() if value})

        # Start from the required skeleton so missing values are reported as
        # e.g. database.dsn (with its env var) rather than a missing section.
        data: dict = {"database": {}, "models": {"generator": {}}}
        for key, value in values.items():
            *parents, leaf = ENV_FIELDS[key]
            node = data
            for part in parents:
                node = node.setdefault(part, {})
            node[leaf] = value
        return cls._validate(data, source="environment")

    @classmethod
    def _validate(cls, data: dict, source: str) -> "AnalystConfig":
        try:
            return cls.model_validate(data)
        except ValidationError as error:
            raise _config_error(error, source) from None


def _config_error(error: ValidationError, source: str) -> ConfigError:
    lines = [f"Invalid askyourdb configuration ({source}):"]
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"])
        env_var = ENV_VAR_BY_FIELD.get(field)
        hint = f" (TOML key '{field}', env {env_var})" if env_var else ""
        lines.append(f"- {field or 'config'}: {item['msg']}{hint}")
    return ConfigError("\n".join(lines))
