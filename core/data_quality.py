"""Central data-quality states and fail-closed snapshot contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Mapping


class DataAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    MISSING = "MISSING"
    INVALID = "INVALID"
    RECOVERING = "RECOVERING"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


@dataclass(frozen=True)
class DataQualitySnapshot:
    source: str
    symbol: str
    timeframe: str
    state: DataAvailability
    expected_records: int
    received_records: int
    persisted_records: int
    missing_intervals: int
    duplicate_records: int
    invalid_records: int
    stale_records: int
    completeness_percent: float
    reason: str = ""
    provenance: Mapping[str, str] | None = None

    def to_dict(self) -> dict:
        value = asdict(self)
        value["state"] = self.state.value
        return value


class CentralDataQuality:
    """Converts incomplete sources into an explicit, machine-readable state."""

    @staticmethod
    def assess(
        *,
        source: str,
        symbol: str,
        timeframe: str,
        expected: int,
        received: int,
        persisted: int,
        missing: int = 0,
        duplicates: int = 0,
        invalid: int = 0,
        stale: int = 0,
        provider_available: bool = True,
        recovering: bool = False,
        provenance: Mapping[str, str] | None = None,
    ) -> DataQualitySnapshot:
        if not provider_available:
            state = DataAvailability.SOURCE_UNAVAILABLE
            reason = "provider unavailable"
        elif recovering:
            state = DataAvailability.RECOVERING
            reason = "historical recovery in progress"
        elif expected <= 0:
            state = DataAvailability.MISSING
            reason = "expected record window unavailable"
        elif stale > 0:
            state = DataAvailability.STALE
            reason = "one or more required records are stale"
        elif invalid > 0:
            state = DataAvailability.INVALID
            reason = "invalid OHLCV or timestamp data rejected"
        elif missing > 0:
            state = DataAvailability.PARTIAL
            reason = "missing intervals prevent full coverage"
        elif received == 0:
            state = DataAvailability.MISSING
            reason = "no records received"
        elif persisted != received:
            state = DataAvailability.PARTIAL
            reason = "not every received record was persisted"
        elif duplicates > 0:
            state = DataAvailability.PARTIAL
            reason = "duplicate records detected and deduplicated"
        else:
            state = DataAvailability.AVAILABLE
            reason = "complete dataset"

        completeness = 0.0
        if expected > 0:
            completeness = round(min(100.0, max(0.0, 100.0 * persisted / expected)), 4)
        return DataQualitySnapshot(
            source=source,
            symbol=symbol,
            timeframe=timeframe,
            state=state,
            expected_records=max(0, int(expected)),
            received_records=max(0, int(received)),
            persisted_records=max(0, int(persisted)),
            missing_intervals=max(0, int(missing)),
            duplicate_records=max(0, int(duplicates)),
            invalid_records=max(0, int(invalid)),
            stale_records=max(0, int(stale)),
            completeness_percent=completeness,
            reason=reason,
            provenance=dict(provenance or {}),
        )

    @staticmethod
    def safe_for_inference(reports: Iterable[DataQualitySnapshot]) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        for report in reports:
            if report.state is not DataAvailability.AVAILABLE:
                reasons.append(f"{report.source}/{report.symbol}/{report.timeframe}:{report.state.value}:{report.reason}")
        return not reasons, reasons
