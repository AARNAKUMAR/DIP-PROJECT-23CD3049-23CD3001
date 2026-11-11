"""DIP-only region summaries supplied to the canonical feature builder."""

import numpy as np
from numpy.typing import NDArray


def current_row_region_features(
    mask: NDArray[np.uint8],
    validity_mask: NDArray[np.bool_],
) -> dict[str, float]:
    """Summarize foreground density, channel count, and persistence at window end."""

    if mask.ndim != 2 or mask.shape != validity_mask.shape:
        raise ValueError("DIP mask and validity mask must be matching 2D arrays")
    foreground = (mask > 0) & validity_mask
    current_row = foreground[-1]
    valid_count = int(validity_mask[-1].sum())
    affected_channel_count = int(current_row.sum())

    channel_persistence: list[int] = []
    for channel_index in np.flatnonzero(current_row):
        channel_length = 0
        for row_index in range(foreground.shape[0] - 1, -1, -1):
            if not foreground[row_index, channel_index]:
                break
            channel_length += 1
        channel_persistence.append(channel_length)
    persistence = max(channel_persistence, default=0)

    return {
        "dip_max_region_persistence": float(persistence),
        "dip_region_density": affected_channel_count / valid_count if valid_count else 0.0,
        "dip_affected_channel_count": float(affected_channel_count),
    }
