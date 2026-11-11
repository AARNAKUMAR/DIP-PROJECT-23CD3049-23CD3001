"""Validated application settings loaded from YAML and environment."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class QualitySettings(BaseModel):
    """Configured thresholds for the single structured quality engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    null_rate_max: float = Field(ge=0.0, le=1.0)
    duplicate_rate_max: float = Field(ge=0.0, le=1.0)
    row_count_drop_max: float = Field(ge=0.0, le=1.0)
    distribution_z_score_max: float = Field(gt=0.0)
    field_ranges: dict[str, tuple[float, float]]

    @model_validator(mode="after")
    def validate_ranges(self) -> "QualitySettings":
        """Reject configured ranges whose minimum exceeds their maximum."""

        invalid_fields = [name for name, (minimum, maximum) in self.field_ranges.items() if minimum > maximum]
        if invalid_fields:
            raise ValueError(f"Invalid configured ranges for fields: {', '.join(sorted(invalid_fields))}")
        return self


class FeatureSettings(BaseModel):
    """Stable canonical feature order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    names: tuple[str, ...]
    dip_region_names: tuple[str, ...]

    @model_validator(mode="after")
    def validate_feature_names(self) -> "FeatureSettings":
        names = self.names + self.dip_region_names
        if not self.names or not self.dip_region_names or len(set(names)) != len(names):
            raise ValueError("Structured and DIP feature names must be non-empty and unique")
        return self


class DetectionSettings(BaseModel):
    """Parameters for the primary unsupervised detector and baseline policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str
    random_state: int
    n_estimators: int = Field(ge=1)
    max_samples: float = Field(gt=0.0, le=1.0)
    contamination: Literal["auto"] | float
    max_features: float = Field(gt=0.0, le=1.0)
    bootstrap: bool
    n_jobs: int = Field(ge=1)
    baseline_severities: tuple[Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"], ...]
    ablation_dip_method: Literal["DIP-B0", "DIP-P1"]

    @model_validator(mode="after")
    def validate_contamination(self) -> "DetectionSettings":
        if self.contamination != "auto" and not 0.0 < self.contamination <= 0.5:
            raise ValueError("Isolation Forest contamination must be 'auto' or a fraction in (0, 0.5]")
        return self


class EvaluationSettings(BaseModel):
    """Train/validation/test split and artifact paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    training_group_fraction: float = Field(gt=0.0, lt=1.0)
    validation_group_fraction: float = Field(gt=0.0, lt=1.0)
    output_dir: Path
    model_dir: Path

    @model_validator(mode="after")
    def validate_split_fractions(self) -> "EvaluationSettings":
        if self.training_group_fraction + self.validation_group_fraction >= 1.0:
            raise ValueError("Training and validation fractions must leave a non-empty test partition")
        return self


class RetrievalSettings(BaseModel):
    """Local runbook retrieval configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runbooks_dir: Path
    top_k: int = Field(ge=1)


class RCASettings(BaseModel):
    """Evidence thresholds used by deterministic RCA rules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_spike_ratio: float = Field(gt=1.0)


class ActionSettings(BaseModel):
    """Safe local action and approval configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_dir: Path
    approval_required_tools: tuple[Literal["simulate_repair"], ...]
    approval_role: str


class PersistenceSettings(BaseModel):
    """Local SQLite persistence configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    database_path: Path


class DIPSettings(BaseModel):
    """Validated encoder, processor, and artifact settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    encoder_version: str
    baseline_version: str
    window_size: int = Field(ge=11)
    channel_order: tuple[str, ...] = Field(min_length=2)
    robust_scale_k: float = Field(gt=0.0)
    scale_floor: float = Field(gt=0.0)
    artifact_dir: Path
    threshold_method: Literal["otsu", "fixed"]
    fixed_threshold: int = Field(ge=0, le=255)
    median_filter_enabled: bool
    median_kernel_size: int = Field(gt=1)
    adaptive_block_size: int = Field(gt=1)
    adaptive_c: float
    morphology_operation: Literal["none", "open", "close", "open_close"]
    morphology_kernel_size: int = Field(gt=1)
    connected_components_connectivity: Literal[4, 8]
    region_match_iou_min: float = Field(gt=0.0, le=1.0)
    evaluation_dir: Path
    window_stride: int = Field(ge=1)
    training_group_fraction: float = Field(gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def validate_operator_parameters(self) -> "DIPSettings":
        """Validate odd kernels and ensure local threshold fits the fingerprint."""

        for field_name in ("median_kernel_size", "adaptive_block_size", "morphology_kernel_size"):
            value = getattr(self, field_name)
            if value % 2 == 0:
                raise ValueError(f"{field_name} must be odd")
        if self.adaptive_block_size >= min(self.window_size, len(self.channel_order)):
            raise ValueError("adaptive_block_size must be smaller than both fingerprint dimensions")
        if len(set(self.channel_order)) != len(self.channel_order):
            raise ValueError("DIP channel_order entries must be unique")
        if self.window_stride > self.window_size:
            raise ValueError("window_stride cannot exceed window_size because that would leave gaps")
        return self


class Settings(BaseSettings):
    """Application settings shared by the composition root and services."""

    model_config = SettingsConfigDict(
        yaml_file=PROJECT_ROOT / "configs" / "default.yaml",
        env_prefix="DATAGUARD_",
        extra="forbid",
    )

    app_name: str
    environment: str
    log_level: str
    api_host: str
    api_port: int = Field(ge=1, le=65535)
    dashboard_api_base_url: str
    synthetic_seed: int
    runs_per_scenario: int = Field(ge=1)
    scenario_persistence_runs: int = Field(ge=1)
    data_output_dir: Path
    quality: QualitySettings
    features: FeatureSettings
    dip: DIPSettings
    detection: DetectionSettings
    evaluation: EvaluationSettings
    retrieval: RetrievalSettings
    rca: RCASettings
    actions: ActionSettings
    persistence: PersistenceSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Use explicit overrides first, then environment, then project YAML."""

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    @property
    def resolved_data_output_dir(self) -> Path:
        """Return the configured data directory resolved against the repository."""

        if self.data_output_dir.is_absolute():
            return self.data_output_dir
        return PROJECT_ROOT / self.data_output_dir

    @property
    def resolved_dip_artifact_dir(self) -> Path:
        """Return the configured DQF artifact directory under the project."""

        return self._resolve_path(self.dip.artifact_dir)

    @property
    def resolved_dip_evaluation_dir(self) -> Path:
        """Return the configured DIP evaluation directory under the project."""

        return self._resolve_path(self.dip.evaluation_dir)

    @property
    def resolved_evaluation_dir(self) -> Path:
        """Return the configured detector evaluation output directory."""

        return self._resolve_path(self.evaluation.output_dir)

    @property
    def resolved_model_dir(self) -> Path:
        """Return the configured local model artifact directory."""

        return self._resolve_path(self.evaluation.model_dir)

    @property
    def resolved_runbooks_dir(self) -> Path:
        """Return the configured local runbook corpus directory."""

        return self._resolve_path(self.retrieval.runbooks_dir)

    @property
    def resolved_action_artifact_dir(self) -> Path:
        """Return the isolated directory for simulated action artifacts."""

        return self._resolve_path(self.actions.artifact_dir)

    @property
    def resolved_database_path(self) -> Path:
        """Return the configured SQLite database path."""

        return self._resolve_path(self.persistence.database_path)

    @staticmethod
    def _resolve_path(path: Path) -> Path:
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate settings once per process."""

    return Settings()
