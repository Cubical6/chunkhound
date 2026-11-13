"""Project-only settings for deterministic structure extraction."""

from pydantic import BaseModel, ConfigDict, Field


class TechnicalTablesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class DomainConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    technical_tables: TechnicalTablesConfig = Field(
        default_factory=TechnicalTablesConfig
    )
