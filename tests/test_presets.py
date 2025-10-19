from bslfs.terps.runner import PRESETS, preset_overrides


def test_preset_overrides_contains_expected_keys():
    overrides = preset_overrides("0p02")
    assert "mode=RECIP" in overrides
    assert "tau_ms=100.0" in overrides
    assert "adc.gain=16" in overrides
    assert "adc.rate_sps=50" in overrides


def test_presets_defined():
    assert set(PRESETS) == {"0p02", "0p01", "0p003"}
