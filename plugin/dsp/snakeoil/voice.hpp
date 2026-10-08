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

// Block-wide synth parameters, mirroring the fields the Python Voice reads.
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

    double amp_attack = kAmpAttack;
    double amp_decay = kAmpDecay;
    double amp_sustain = kAmpSustain;
    double amp_release = kAmpRelease;

    double flt_attack = kFltAttack;
    double flt_decay = kFltDecay;
    double flt_sustain = kFltSustain;
    double flt_release = kFltRelease;
    double flt_env_amount = 0.0;
    double flt_keytrack = 0.0;
    double flt_vel = 0.0;

    bool lpf_in_voice = true;
    bool lpf_active = true;
    bool lpf_ladder = false;
    bool mod_filter = false;
    BiquadCoeffs lpf12{};
    BiquadPair lpf24{};
    double lpf_cutoff = kDefaultLpfCutoff;
    double lpf_resonance = 0.0;

    double lfo_pitch_ratio = 1.0;
    double lfo_filter_oct = 0.0;
    double lfo_pwm = 0.0;
    const double* lfo_amp = nullptr;

    double noise_level = 0.0;
    const std::vector<double>* noise_table = nullptr;

    double master_gain = kDefaultMasterGain;
};

class Voice {
public:
    explicit Voice(double sampleRate)
        : sr_(sampleRate), osc1_(sampleRate, false), osc2_(sampleRate, true),
          env_(sampleRate), fltEnv_(sampleRate) {
        fltEnv_.setShape(kFltAttack, kFltDecay, kFltSustain, kFltRelease);
    }

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
    void noteOn(int note, double velocity, long order, bool stolen,
                double glideFrom, double glideTime, long long noisePos,
                double detuneCents = 0.0, double pan = 0.0, double gain = 1.0,
                bool randomPhase = false, double phase1 = 0.0, double phase2 = 0.0) {
        note_ = note;
        gate_ = true;
        freq_ = midiNoteToFreq(note);
        velocity_ = velocity;
        triggerOrder_ = order;
        noisePos_ = noisePos;
        detuneCents_ = detuneCents;
        pan_ = pan;
        gain_ = gain;
        gliding_ = glideFrom > 0.0 && glideTime > 0.0;
        glideFrom_ = glideFrom;
        glideTotal_ = glideTime;
        glidePos_ = 0.0;
        if (stolen) {
            env_.noteOn(true);
            fltEnv_.setIdle();
            fltEnv_.noteOn();
            return;
        }
        if (randomPhase) {
            osc1_.setPhase(phase1);
            osc2_.setPhase(phase2);
        } else {
            osc1_.reset();
            osc2_.reset();
        }
        env_.noteOn();
        fltEnv_.setIdle();
        fltEnv_.noteOn();
        lpf_.reset();
        oscPhase_ = 0.0;
    }

    double pan() const { return pan_; }

    void noteOff() {
        gate_ = false;
        env_.noteOff();
        fltEnv_.noteOff();
    }

    // Release quickly (a short linear fade) instead of cutting the voice, used
    // when the hybrid allocator has to free a playable voice.
    void forceRelease(double seconds) {
        gate_ = false;
        env_.noteOff(seconds);
        fltEnv_.noteOff();
    }

    int groupId() const { return group_; }
    void setGroup(int group) { group_ = group; }

    void render(int n, const Params& p, double* out) {
        env_.setShape(p.amp_attack, p.amp_decay, p.amp_sustain, p.amp_release);
        fltEnv_.setShape(p.flt_attack, p.flt_decay, p.flt_sustain, p.flt_release);

        osc1_.setLayerSquare(p.osc1_square);
        osc1_.setSquareLevel(p.osc1_square_level);
        if (p.lfo_pwm != 0.0) {
            osc1_.setDuty(std::min(std::max(p.osc1_pwm + p.lfo_pwm, 0.0), 0.5));
            osc2_.setDuty(std::min(std::max(p.osc2_pwm + p.lfo_pwm, 0.0), 0.5));
        } else {
            osc1_.setDuty(p.osc1_pwm);
            osc2_.setDuty(p.osc2_pwm);
        }
        double base = freq_;
        if (gliding_) {
            const double centre = glidePos_ + 0.5 * n / sr_;
            const double remaining = std::max(0.0, 1.0 - centre / glideTotal_);
            if (remaining > 0.0) {
                base = std::exp(std::log(base) +
                                (std::log(glideFrom_) - std::log(base)) * remaining);
            }
            glidePos_ += n / sr_;
            if (glidePos_ >= glideTotal_) {
                gliding_ = false;
            }
        }
        const double freq = base * p.pitch_ratio * p.lfo_pitch_ratio;
        const double f2 = freq * semitonesToRatio(p.detune2_semitones, p.detune2_cents) *
                          (p.osc2_octave_up ? 2.0 : 1.0);
        const double f1 = freq * (p.osc1_octave_down ? 0.5 : 1.0);
        double f1d = f1;
        double f2d = f2;
        if (detuneCents_ != 0.0) {
            const double ud = std::pow(2.0, detuneCents_ / 1200.0);
            f1d *= ud;
            f2d *= ud;
        }
        const double limit = 0.45 * sr_;
        const double f1c = std::min(f1d, limit);
        const double f2c = std::min(f2d, limit);
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

        if (p.noise_level > 0.0 && p.noise_table != nullptr && !p.noise_table->empty()) {
            const std::vector<double>& tbl = *p.noise_table;
            const long long size = static_cast<long long>(tbl.size());
            const long long pos = noisePos_ % size;
            for (int k = 0; k < n; ++k) {
                mix_[k] += p.noise_level * tbl[static_cast<std::size_t>((pos + k) % size)];
            }
            noisePos_ = (pos + n) % size;
        }

        if (p.lpf_in_voice) {
            applyVoiceFilter(n, p);
        }

        env_.process(envBuf_.data(), n);
        const double amp = 0.22 * (0.3 + 0.7 * velocity_);
        for (int k = 0; k < n; ++k) {
            out[k] += mix_[k] * envBuf_[k] * amp;
        }
        if (p.lfo_amp != nullptr) {
            for (int k = 0; k < n; ++k) {
                out[k] *= p.lfo_amp[k];
            }
        }
        if (gain_ != 1.0) {
            for (int k = 0; k < n; ++k) {
                out[k] *= gain_;
            }
        }
    }

private:
    void applyVoiceFilter(int n, const Params& p) {
        const bool perVoice = p.flt_env_amount != 0.0 || p.flt_keytrack != 0.0 ||
                              p.flt_vel != 0.0 || p.lfo_filter_oct != 0.0 ||
                              p.mod_filter;
        if (!perVoice) {
            if (!p.lpf_active) {
                if (lpfBypassed_) {
                    lpf_.reset();
                    lpfBypassed_ = false;
                }
                return;
            }
            if (lpfBypassed_) {
                lpf_.reset();
                lpfBypassed_ = false;
            }
            if (p.lpf_ladder) {
                lpf_.process(mix_.data(), n, p.lpf24);
                maybeWhistle(n, p, p.lpf_cutoff);
            } else {
                lpf_.process(mix_.data(), n, p.lpf12);
            }
            return;
        }
        double octaves = p.lfo_filter_oct;
        if (p.flt_env_amount != 0.0) {
            fltEnv_.process(envBuf_.data(), n);
            double sum = 0.0;
            for (int k = 0; k < n; ++k) {
                sum += envBuf_[k];
            }
            octaves += p.flt_env_amount * kFltEnvOctaves * (sum / n);
        }
        if (p.flt_keytrack != 0.0) {
            octaves += p.flt_keytrack * (note_ - 60) / 12.0;
        }
        if (p.flt_vel != 0.0) {
            octaves += p.flt_vel * kFltVelOctaves * (velocity_ - 0.5);
        }
        double cutoff = p.lpf_cutoff * std::pow(2.0, octaves);
        cutoff = std::min(std::max(cutoff, kLpfMinHz), 0.45 * sr_);
        if (cutoff >= kLpfMaxHz / 1.01) {
            lpfBypassed_ = true;
            return;
        }
        if (lpfBypassed_) {
            lpf_.reset();
            lpfBypassed_ = false;
        }
        if (p.lpf_ladder) {
            const BiquadPair coeffs = lpf24Coefficients(cutoff, p.lpf_resonance, sr_);
            lpf_.process(mix_.data(), n, coeffs);
            maybeWhistle(n, p, cutoff);
        } else {
            const BiquadCoeffs coeffs = lpfCoefficients(cutoff, p.lpf_resonance, sr_);
            lpf_.process(mix_.data(), n, coeffs);
        }
    }

    void maybeWhistle(int n, const Params& p, double cutoff) {
        if (!p.lpf_ladder || p.lpf_resonance <= kLadderOscStart) {
            return;
        }
        const double t = std::min(
            (p.lpf_resonance - kLadderOscStart) / (1.0 - kLadderOscStart), 1.0);
        const double level = kLadderOscLevel * t * t * (3.0 - 2.0 * t);
        const double step = 2.0 * kPi * cutoff / sr_;
        for (int k = 0; k < n; ++k) {
            mix_[k] += level * std::sin(oscPhase_ + step * (k + 1));
        }
        oscPhase_ = std::fmod(oscPhase_ + step * n, 2.0 * kPi);
    }

    double sr_;
    Oscillator osc1_;
    Oscillator osc2_;
    Envelope env_;
    Envelope fltEnv_;
    LowPass lpf_;
    int note_ = -1;
    bool gate_ = false;
    double freq_ = 0.0;
    double velocity_ = 0.0;
    long triggerOrder_ = 0;
    int group_ = -1;
    bool lpfBypassed_ = false;
    double oscPhase_ = 0.0;
    bool gliding_ = false;
    double glideFrom_ = 0.0;
    double glideTotal_ = 0.0;
    double glidePos_ = 0.0;
    long long noisePos_ = 0;
    double detuneCents_ = 0.0;
    double pan_ = 0.0;
    double gain_ = 1.0;
    std::vector<double> mod_, sec_, phaseMod_, envBuf_, mix_, ramp_;
};

}  // namespace snakeoil
