from __future__ import annotations


from igchat.direct.voice import format_voice_note_metadata, generate_waveform_peaks


def test_waveform_generation():
    audio_sample = bytes([10, 50, 120, 200, 255, 180, 90, 20] * 16)
    peaks = generate_waveform_peaks(audio_sample, num_peaks=32)
    assert len(peaks) == 32
    assert all(0.0 <= p <= 1.0 for p in peaks)


def test_voice_note_metadata():
    wf = [0.1, 0.5, 0.9]
    meta = format_voice_note_metadata(duration_ms=4500, waveform=wf)
    assert meta["item_type"] == "voice_media"
    assert meta["audio_duration_ms"] == 4500
    assert meta["audio_waveform_data"] == wf
    assert meta["is_voice_clip"] is True
