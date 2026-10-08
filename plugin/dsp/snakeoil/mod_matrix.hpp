#pragma once

#include <algorithm>
#include <cmath>
#include <string>

#include "snakeoil/constants.hpp"

namespace snakeoil {

// Mod matrix sources (indices match the Python SOURCES tuple).
enum { kSrcNone = 0, kSrcNote = 1, kSrcLfo1 = 2, kSrcLfo2 = 3, kSrcWheel = 4,
       kSrcAftertouch = 5 };

constexpr double kModSmooth = 0.3;

inline int sourceIndex(const std::string& name) {
    if (name == "Note Number") return kSrcNote;
    if (name == "LFO 1") return kSrcLfo1;
    if (name == "LFO 2") return kSrcLfo2;
    if (name == "Mod Wheel") return kSrcWheel;
    if (name == "Aftertouch") return kSrcAftertouch;
    return kSrcNone;
}

inline double noteSource(int note) {
    return std::min(std::max((note - 60) / 60.0, -1.0), 1.0);
}

inline double effective(double base, double total, double lo, double hi) {
    return std::min(std::max(base * (1.0 + total), lo), hi);
}

inline double smoothStep(double current, double target) {
    return current + kModSmooth * (target - current);
}

// Destinations the C++ engine understands, with their clamp range and whether
// they live on the voice/filter params or on the effect dials. Names match the
// Python DEST_NAMES.
struct ModDest {
    const char* name;
    const char* paramId;
    bool fx;
    double lo;
    double hi;
};

inline const ModDest* modDestinations(int& count) {
    static const ModDest kDests[] = {
        {"Osc 1: Level", "osc1_level", false, 0.0, 1.0},
        {"Osc 1: PWM", "osc1_pwm", false, 0.0, 0.5},
        {"Osc 1: Sq Level", "osc1_square_level", false, 0.0, 1.0},
        {"Osc 2: Level", "osc2_level", false, 0.0, 1.0},
        {"Osc 2: Tune", "detune2_semitones", false, kSemitoneMin, kSemitoneMax},
        {"Osc 2: Fine", "detune2_cents", false, kCentsMin, kCentsMax},
        {"Osc 2: PWM", "osc2_pwm", false, 0.0, 0.5},
        {"Noise: Level", "noise_level", false, 0.0, 1.0},
        {"Modulation Amount", "fm_depth", false, 0.0, 1.0},
        {"Filter: Cutoff", "lpf_cutoff", false, kLpfMinHz, kLpfMaxHz},
        {"Filter: Resonance", "lpf_resonance", false, 0.0, 1.0},
        {"Filter: Env Amount", "flt_env_amount", false, -1.0, 1.0},
        {"Filter: Key Trk", "flt_keytrack", false, 0.0, 1.0},
        {"Filter: Vel>Cut", "flt_vel", false, 0.0, 1.0},
        {"Filter Env: Attack", "flt_attack", false, 0.001, 5.0},
        {"Filter Env: Decay", "flt_decay", false, 0.001, 5.0},
        {"Filter Env: Sustain", "flt_sustain", false, 0.0, 1.0},
        {"Filter Env: Release", "flt_release", false, 0.001, 10.0},
        {"Amp Env: Attack", "amp_attack", false, 0.001, 5.0},
        {"Amp Env: Decay", "amp_decay", false, 0.001, 5.0},
        {"Amp Env: Sustain", "amp_sustain", false, 0.0, 1.0},
        {"Amp Env: Release", "amp_release", false, 0.001, 10.0},
        {"Chorus: Depth", "fx_chorus_depth", true, 0.0, 1.0},
        {"Delay: Time", "fx_delay_time", true, 1.0, 4000.0},
        {"Delay: Feedback", "fx_delay_feedback", true, 0.0, 0.95},
        {"Delay: Tone", "fx_delay_damp", true, 0.0, 0.9},
        {"Reverb: Amount", "fx_reverb_amount", true, 0.0, 1.0},
        {"Reverb: Size", "fx_reverb_size", true, 0.5, 0.98},
        {"Reverb: Damping", "fx_reverb_damp", true, 0.0, 0.9},
        {"Bitcrush: Crush", "fx_bitcrush_amount", true, 0.0, 1.0},
    };
    count = static_cast<int>(sizeof(kDests) / sizeof(kDests[0]));
    return kDests;
}

}  // namespace snakeoil
