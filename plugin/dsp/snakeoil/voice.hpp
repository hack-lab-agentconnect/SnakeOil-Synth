#pragma once

#include <algorithm>
#include <cmath>
#include <vector>

#include "snakeoil/biquad.hpp"
#include "snakeoil/constants.hpp"
#include "snakeoil/envelope.hpp"
#include "snakeoil/oscillator.hpp"

namespace snakeoil {

inline double midiNoteToFreq(int note) {
    return 440.0 * std::pow(2.0, (note - 69) / 12.0);
}

inline double semitonesToRatio(double semitones, double cents = 0.0) {
    return std::pow(2.0, (semitones + cents / 100.0) / 12.0);
}

enum class Mode { kOff, kFm, kAm, kRing, kSync };

// Block-wide synth parameters. A subset of the Python params dict: the fields
// the default signal path reads. Later phases add noise, per-voice filter
// modulation and the mod matrix.
struct Params {
    double osc1_level = 1.0;
    double osc2_level = 0.0;
    bool osc1_square = true;
    double osc1_square_level = kDefaultSquareLevel;
    double osc1_pwm = kDefaultPwm;
    double osc2_pwm = kDefaultPwm;
    Mode mod_mode = Mode::kFm;
    double fm_depth = 0.0;
    double mod_index = 0.0;
    double detune2_semitones = 0.0;
    double detune2_cents = 0.0;
    bool osc1_octave_down = false;
    bool osc2_octave_up = true;
    double pitch_ratio = 1.0;
    bool lpf_in_voice = true;
    bool lpf_active = true;
    BiquadCoeffs lpf{kDefaultLpfCutoff, kDefaultLpfCutoff, kDefaultLpfCutoff, 0.0, 0.0};
    double master_gain = kDefaultMasterGain;
};

class Voice {
public:
    explicit Voice(double sampleRate)
        : sr_(sampleRate), osc1_(sampleRate, false), osc2_(sampleRate, true),
          env_(sampleRate) {}

    bool active() const { return env_.active(); }
    bool gated() const { return gate_; }
    int note() const { return note_; }
    long triggerOrder() const { return triggerOrder_; }
    double envLevel() const { return env_.level(); }

    void prepare(int maxBlock) {
        if (static_cast<int>(mod_.size()) < maxBlock) {
            mod_.resize(maxBlock);
            sec_.resize(maxBlock);
            phaseMod_.resize(maxBlock);
            envBuf_.resize(maxBlock);
            mix_.resize(maxBlock);
            ramp_.resize(maxBlock);
        }
    }

    // ``velocity`` is normalised 0..1 (the engine divides the MIDI value).
    void noteOn(int note, double velocity, long order, bool stolen) {
        note_ = note;
        gate_ = true;
        freq_ = midiNoteToFreq(note);
        velocity_ = velocity;
        triggerOrder_ = order;
        if (stolen) {
            env_.noteOn(true);
            return;
        }
        osc1_.reset();
        osc2_.reset();
        env_.noteOn();
        lpf_.reset();
    }

    void noteOff() {
        gate_ = false;
        env_.noteOff();
    }

    void render(int n, const Params& p, double* out) {
        osc1_.setLayerSquare(p.osc1_square);
        osc1_.setSquareLevel(p.osc1_square_level);
        osc1_.setDuty(p.osc1_pwm);
        osc2_.setDuty(p.osc2_pwm);
        const double freq = freq_ * p.pitch_ratio;
        const double f2 = freq * semitonesToRatio(p.detune2_semitones, p.detune2_cents) *
                          (p.osc2_octave_up ? 2.0 : 1.0);
        const double f1 = freq * (p.osc1_octave_down ? 0.5 : 1.0);
        const double limit = 0.45 * sr_;
        const double f1c = std::min(f1, limit);
        const double f2c = std::min(f2, limit);
        const bool audible2 = p.osc2_level != 0.0;

        if (p.mod_mode == Mode::kSync) {
            osc1_.advanceTo(f1c, n, ramp_.data());
            for (int k = 0; k < n; ++k) {
                mod_[k] = osc1_.shape(ramp_[k], f1c);
            }
            if (audible2) {
                osc2_.generate(f2c, n, sec_.data());
                const double ratio = f1c != 0.0 ? f2c / f1c : 1.0;
                for (int k = 0; k < n; ++k) {
                    const double sync = osc2_.shape(mod1(ramp_[k] * ratio), f2c);
                    sec_[k] = sec_[k] * (1.0 - p.fm_depth) + sync * p.fm_depth;
                }
            } else {
                osc2_.advance(f2c, n);
            }
        } else {
            osc1_.generate(f1c, n, mod_.data());
            if (!audible2) {
                osc2_.advance(f2c, n);
            } else if (p.mod_mode == Mode::kFm) {
                for (int k = 0; k < n; ++k) {
                    phaseMod_[k] = mod_[k] * p.mod_index;
                }
                osc2_.generate(f2c, n, sec_.data(), phaseMod_.data());
            } else {
                osc2_.generate(f2c, n, sec_.data());
                if (p.mod_mode == Mode::kAm) {
                    for (int k = 0; k < n; ++k) {
                        sec_[k] *= 1.0 - 0.5 * p.fm_depth + 0.5 * p.fm_depth * mod_[k];
                    }
                } else if (p.mod_mode == Mode::kRing) {
                    for (int k = 0; k < n; ++k) {
                        sec_[k] *= (1.0 - p.fm_depth) + p.fm_depth * mod_[k];
                    }
                }
            }
        }

        for (int k = 0; k < n; ++k) {
            double v = p.osc1_level * mod_[k];
            if (audible2) {
                v += p.osc2_level * sec_[k];
            }
            mix_[k] = v;
        }
        if (p.lpf_in_voice && p.lpf_active) {
            lpf_.process(mix_.data(), n, p.lpf);
        }
        env_.process(envBuf_.data(), n);
        const double amp = 0.22 * (0.3 + 0.7 * velocity_);
        for (int k = 0; k < n; ++k) {
            out[k] += mix_[k] * envBuf_[k] * amp;
        }
    }

private:
    double sr_;
    Oscillator osc1_;
    Oscillator osc2_;
    Envelope env_;
    LowPass lpf_;
    int note_ = -1;
    bool gate_ = false;
    double freq_ = 0.0;
    double velocity_ = 0.0;
    long triggerOrder_ = 0;
    std::vector<double> mod_, sec_, phaseMod_, envBuf_, mix_, ramp_;
};

}  // namespace snakeoil
