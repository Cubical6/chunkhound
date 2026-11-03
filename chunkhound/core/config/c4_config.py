"""Project settings for the sources of the C4 map."""

from pydantic import BaseModel, Field


class C4Config(BaseModel):
    """Which files the C4 analysis of ``chunkhound map`` may use as a source.

    Only C4 reads this section: HyDE and research keep seeing these files.
    """

    exclude: list[str] = Field(
        default_factory=list,
        description="Patterns from the project root, for code and documentation",
    )
    exclude_test_code: bool = Field(
        default=True,
        description="Leave out test directories and files named as tests",
    )
