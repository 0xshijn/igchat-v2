"""Native Audio Waveform & Voice Note Transcoder for Instagram Direct."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def generate_waveform_peaks(
    audio_data: bytes,
    num_peaks: int = 64,
) -> list[float]:
    """Sample audio byte amplitudes into a normalized list of float peaks (0.0 to 1.0).

    Mimics Instagram's mobile native waveform visualizer envelope.
    """
    if num_peaks <= 0:
        raise ValueError("num_peaks phải là số nguyên dương.")

    if not audio_data:
        # Return resting ambient wave
        return [0.05 + 0.1 * math.sin(i / 3.0) for i in range(num_peaks)]

    # Sample byte values
    total_len = len(audio_data)
    chunk_size = max(1, total_len // num_peaks)
    peaks: list[float] = []

    for i in range(num_peaks):
        start = i * chunk_size
        end = min(total_len, start + chunk_size)
        chunk = audio_data[start:end]
        if not chunk:
            peaks.append(0.05)
            continue

        # Compute peak energy
        max_val = max(chunk)
        # Normalize 0-255 to 0.05-1.0
        normalized = max(0.05, min(1.0, max_val / 255.0))
        peaks.append(round(normalized, 3))

    return peaks


def format_voice_note_metadata(
    duration_ms: int,
    waveform: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Format voice note metadata payload for Instagram Direct RUpload."""
    dur = max(500, int(duration_ms))
    wf = list(waveform) if waveform else [0.2] * 64
    return {
        "item_type": "voice_media",
        "audio_waveform_data": wf,
        "audio_duration_ms": dur,
        "is_voice_clip": True,
    }


__all__ = [
    "format_voice_note_metadata",
    "generate_waveform_peaks",
]
