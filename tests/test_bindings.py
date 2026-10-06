import pytest

from midi_synth.bindings import (
    CC, NOTE, Source, Profile, default_profile, DEFAULT_NAME,
)


def test_source_key_roundtrip_and_label():
    s = Source(CC, 74, 3)
    assert s.key() == "cc:3:74"
    assert Source.from_key("cc:3:74") == s
    assert s.label() == "CC 74 ch3"
    any_ch = Source(NOTE, 60, None)
    assert any_ch.key() == "note:*:60"
    assert Source.from_key("note:*:60") == any_ch
    assert any_ch.label() == "Note 60"


@pytest.mark.parametrize("bad", ["cc:3", "foo:1:2", "cc:17:2", "cc:1:200", "cc:x:2"])
def test_source_from_key_rejects_garbage(bad):
    with pytest.raises(ValueError):
        Source.from_key(bad)


def test_bind_and_lookup_exact_channel():
    p = Profile("t")
    p.bind(Source(CC, 74, 1), "osc1_level")
    assert p.param_for(CC, 1, 74) == "osc1_level"
    assert p.param_for(CC, 2, 74) is None
    assert p.source_for("osc1_level") == Source(CC, 74, 1)


def test_any_channel_binding_matches_all_channels():
    p = Profile("t")
    p.bind(Source(CC, 1, None), "fm_depth")
    assert p.param_for(CC, 1, 1) == "fm_depth"
    assert p.param_for(CC, 16, 1) == "fm_depth"


def test_rebinding_param_moves_it():
    p = Profile("t")
    p.bind(Source(CC, 10, 1), "osc1_level")
    p.bind(Source(CC, 11, 1), "osc1_level")
    assert p.param_for(CC, 1, 10) is None
    assert p.param_for(CC, 1, 11) == "osc1_level"


def test_binding_taken_source_steals_it():
    p = Profile("t")
    p.bind(Source(CC, 10, 1), "osc1_level")
    p.bind(Source(CC, 10, 1), "osc2_level")
    assert p.source_for("osc1_level") is None
    assert p.param_for(CC, 1, 10) == "osc2_level"


def test_exact_binding_steals_overlapping_any_channel_binding():
    p = Profile("t")
    p.bind(Source(CC, 1, None), "fm_depth")
    p.bind(Source(CC, 1, 5), "master_gain")
    assert p.source_for("fm_depth") is None
    assert p.param_for(CC, 5, 1) == "master_gain"


def test_clear():
    p = Profile("t")
    p.bind(Source(CC, 10, 1), "osc1_level")
    assert p.clear("osc1_level") is True
    assert p.clear("osc1_level") is False
    assert p.param_for(CC, 1, 10) is None


def test_dict_roundtrip_and_malformed_entries_skipped():
    p = Profile("t")
    p.bind(Source(CC, 74, 2), "osc1_level")
    p.bind(Source(NOTE, 36, None), "fx_delay")
    data = p.to_dict()
    assert data["version"] == 1
    again = Profile.from_dict("t", data)
    assert sorted(again.items(), key=lambda x: x[1]) == sorted(p.items(), key=lambda x: x[1])

    data["bindings"].append({"source": "nonsense", "param": "x"})
    data["bindings"].append({"nope": 1})
    assert len(Profile.from_dict("t", data).items()) == 2


def test_from_dict_rejects_non_object():
    with pytest.raises(ValueError):
        Profile.from_dict("t", [1, 2, 3])


def test_copy_is_independent():
    p = Profile("a")
    p.bind(Source(CC, 5, 1), "osc1_level")
    q = p.copy("b")
    q.clear("osc1_level")
    assert q.name == "b"
    assert p.source_for("osc1_level") is not None


def test_default_profile_matches_legacy_cc_map():
    p = default_profile()
    assert p.name == DEFAULT_NAME
    expected = {
        7: "master_gain",
        20: "fx_chorus", 21: "fx_delay", 22: "fx_reverb", 23: "fx_bitcrush",
        26: "detune2_semitones", 27: "detune2_cents",
        28: "osc2_level", 29: "osc1_level", 30: "mod_mode",
        71: "lpf_resonance", 74: "lpf_cutoff",
    }
    for cc, pid in expected.items():
        assert p.param_for(CC, 9, cc) == pid
    assert len(p.items()) == len(expected)


def test_default_profile_has_no_waveform_ccs():
    p = default_profile()
    assert p.param_for(CC, 0, 24) is None
    assert p.param_for(CC, 0, 25) is None
