"""The sole owner of fingerprint image processing and segmentation."""

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from datagard.config import DIPSettings
from datagard.contracts import DIPRegion
from datagard.dip.encoder import Fingerprint


@dataclass(frozen=True)
class SegmentationResult:
    """One algorithm's mask, mapped components, overlay, and duration."""

    method: Literal["DIP-B0", "DIP-P1"]
    mask: NDArray[np.uint8]
    component_labels: NDArray[np.int32]
    overlay: NDArray[np.uint8]
    regions: tuple[DIPRegion, ...]
    duration_ms: float


@dataclass(frozen=True)
class DIPProcessingResult:
    """Baseline and improved outputs for the same encoded image."""

    baseline: SegmentationResult
    improved: SegmentationResult
    filtered_image: NDArray[np.uint8]
    adaptive_mask: NDArray[np.uint8]


def process_fingerprint(fingerprint: Fingerprint, settings: DIPSettings) -> DIPProcessingResult:
    """Run configured global baseline and adaptive/morphological alternatives."""

    if fingerprint.pixels.dtype != np.uint8 or fingerprint.pixels.ndim != 2:
        raise ValueError("Fingerprint must be a two-dimensional uint8 grayscale image")
    if fingerprint.pixels.shape != fingerprint.validity_mask.shape:
        raise ValueError("Fingerprint and validity mask shapes differ")
    if min(fingerprint.pixels.shape) < settings.adaptive_block_size:
        raise ValueError("Fingerprint is too small for configured adaptive threshold window")

    baseline_started = perf_counter()
    if settings.threshold_method == "otsu":
        _, baseline_mask = cv2.threshold(
            fingerprint.pixels, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )
    else:
        _, baseline_mask = cv2.threshold(
            fingerprint.pixels, settings.fixed_threshold, 255, cv2.THRESH_BINARY
        )
    baseline_mask = _apply_validity(baseline_mask, fingerprint.validity_mask)
    baseline_labels, baseline_regions = _extract_regions(
        "DIP-B0", baseline_mask, fingerprint, settings.connected_components_connectivity
    )
    baseline_overlay = _create_overlay(fingerprint.pixels, baseline_mask, (0, 70, 255))
    baseline_result = SegmentationResult(
        "DIP-B0",
        baseline_mask,
        baseline_labels,
        baseline_overlay,
        baseline_regions,
        (perf_counter() - baseline_started) * 1000.0,
    )

    improved_started = perf_counter()
    filtered = fingerprint.pixels
    if settings.median_filter_enabled:
        filtered = cv2.medianBlur(filtered, settings.median_kernel_size)
    improved_mask = cv2.adaptiveThreshold(
        filtered,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        settings.adaptive_block_size,
        settings.adaptive_c,
    )
    adaptive_mask = improved_mask.copy()
    improved_mask = _apply_morphology(improved_mask, settings)
    improved_mask = _apply_validity(improved_mask, fingerprint.validity_mask)
    improved_labels, improved_regions = _extract_regions(
        "DIP-P1", improved_mask, fingerprint, settings.connected_components_connectivity
    )
    improved_overlay = _create_overlay(fingerprint.pixels, improved_mask, (0, 220, 80))
    improved_result = SegmentationResult(
        "DIP-P1",
        improved_mask,
        improved_labels,
        improved_overlay,
        improved_regions,
        (perf_counter() - improved_started) * 1000.0,
    )
    return DIPProcessingResult(baseline_result, improved_result, filtered.copy(), adaptive_mask)


def save_grayscale(path: Path, image: NDArray[np.uint8]) -> None:
    """Write a grayscale image and report filesystem failures explicitly."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise OSError(f"OpenCV could not write image: {path}")


def save_color(path: Path, image: NDArray[np.uint8]) -> None:
    """Write a BGR overlay and report filesystem failures explicitly."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise OSError(f"OpenCV could not write image: {path}")


def _apply_morphology(image: NDArray[np.uint8], settings: DIPSettings) -> NDArray[np.uint8]:
    if settings.morphology_operation == "none":
        return image
    shape = cv2.MORPH_ELLIPSE
    kernel = cv2.getStructuringElement(
        shape, (settings.morphology_kernel_size, settings.morphology_kernel_size)
    )
    operations = {
        "open": (cv2.MORPH_OPEN,),
        "close": (cv2.MORPH_CLOSE,),
        "open_close": (cv2.MORPH_OPEN, cv2.MORPH_CLOSE),
    }[settings.morphology_operation]
    result = image
    for operation in operations:
        result = cv2.morphologyEx(result, operation, kernel)
    return result


def _apply_validity(image: NDArray[np.uint8], validity: NDArray[np.bool_]) -> NDArray[np.uint8]:
    return cv2.bitwise_and(image, image, mask=validity.astype(np.uint8) * 255)


def _extract_regions(
    method: str,
    mask: NDArray[np.uint8],
    fingerprint: Fingerprint,
    connectivity: Literal[4, 8],
) -> tuple[NDArray[np.int32], tuple[DIPRegion, ...]]:
    component_count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8), connectivity=connectivity
    )
    regions: list[DIPRegion] = []
    for component_id in range(1, component_count):
        x, y, width, height, area = (int(value) for value in stats[component_id])
        component_pixels = mask[y : y + height, x : x + width]
        region_runs = fingerprint.run_ids[y : y + height]
        region_channels = fingerprint.channel_ids[x : x + width]
        regions.append(
            DIPRegion(
                method=method,
                component_id=component_id,
                x=x,
                y=y,
                width=width,
                height=height,
                centroid_x=float(centroids[component_id, 0]),
                centroid_y=float(centroids[component_id, 1]),
                area=area,
                peak_intensity=int(component_pixels.max(initial=0)),
                density=area / float(width * height),
                run_ids=tuple(region_runs),
                channel_ids=tuple(region_channels),
            )
        )
    return labels.astype(np.int32, copy=False), tuple(regions)


def label_mask_components(
    mask: NDArray[np.uint8],
    validity_mask: NDArray[np.bool_],
    connectivity: Literal[4, 8],
) -> NDArray[np.int32]:
    """Label valid foreground components for region-level evaluation."""

    if mask.shape != validity_mask.shape:
        raise ValueError("Segmentation and validity mask shapes differ")
    foreground = ((mask > 0) & validity_mask).astype(np.uint8)
    _, labels = cv2.connectedComponents(foreground, connectivity=connectivity)
    return labels.astype(np.int32, copy=False)


def _create_overlay(
    grayscale: NDArray[np.uint8], mask: NDArray[np.uint8], color: tuple[int, int, int]
) -> NDArray[np.uint8]:
    background = cv2.cvtColor(grayscale, cv2.COLOR_GRAY2BGR)
    region_color = np.zeros_like(background)
    region_color[mask > 0] = color
    return cv2.addWeighted(background, 0.72, region_color, 0.68, 0.0)
