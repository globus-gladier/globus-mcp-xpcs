from pydantic import BaseModel, Field


class XPCSBoostCorrResult(BaseModel):
    result: str = Field(description="Task outcome, typically 'SUCCEEDED' or 'FAILED'.")
    returncode: int = Field(
        description="Exit code returned by the boost_corr executable."
    )
    execution_time_seconds: float = Field(description="Elapsed runtime in seconds.")
    stdout: str | None = Field(
        default=None,
        description="Optional trailing stdout snippet when debug mode is enabled.",
    )
    stderr: str | None = Field(
        default=None,
        description="Optional trailing stderr snippet when debug mode is enabled.",
    )
