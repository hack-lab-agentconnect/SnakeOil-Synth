#pragma once

#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

#include "snakeoil/biquad.hpp"
#include "snakeoil/constants.hpp"
#include "snakeoil/voice.hpp"

namespace snakeoil {

// Minimal engine for phase P1: 12 classic voices, one shared 12 dB low-pass,
// master gain and tanh. Mirrors SynthEngine.render for the default scenario
// (no effects, no LFO, no mod matrix, unison off).
class Engine {
public:
    Engine(double sampleRate, int blockSize, int maxVoices = kMaxVoices)
        : sr_(sampleRate), blockSize_(blockSize), maxVoices_(std::min(maxVoices, kMaxVoices)) {
        for (int i = 0; i < maxVoices_; ++i) {
            voices_.emplace_back(sampleRate);
        }
        prepare(blockSize);
        updateLpf();
    }

    Params& params() { return params_; }
    const Params& params() const { return params_; }
    double sampleRate() const { return sr_; }

    int activeVoices() const {
        int count = 0;
        for (const auto& v : voices_) {
            if (v.active()) {
                ++count;
            }
        }
        return count;
    }

    // velocity is the raw MIDI value 0..127, as in SynthEngine.note_on.
    void noteOn(int note, double velocity) {
        for (auto& v : voices_) {
            if (v.active() && v.note() == note && v.gated()) {
                v.noteOff();
            }
        }
        ++order_;
        const double vel = clampUnit(velocity / 127.0);
        Voice& voice = allocate();
        voice.noteOn(note, vel, order_, voice.active());
    }

    void noteOff(int note) {
        for (auto& v : voices_) {
            if (v.note() == note && v.gated()) {
                v.noteOff();
            }
        }
    }

    void allNotesOff() {
        for (auto& v : voices_) {
            if (v.active()) {
                v.noteOff();
            }
        }
    }

    // Parameter setter used by the golden scenario "set" events and the plugin
    // later. Returns false for ids this phase does not know.
    bool setParam(const std::string& id, double value) {
        if (id == "osc1_level") {
            params_.osc1_level = clampUnit(value);
        } else if (id == "osc2_level") {
            params_.osc2_level = clampUnit(value);
        } else if (id == "osc1_square_level") {
            params_.osc1_square_level = clampUnit(value);
        } else if (id == "osc1_pwm") {
            params_.osc1_pwm = clampUnit(value / 0.5) * 0.5;
        } else if (id == "osc2_pwm") {
            params_.osc2_pwm = clampUnit(value / 0.5) * 0.5;
        } else if (id == "fm_depth") {
            params_.fm_depth = clampUnit(value);
            params_.mod_index = params_.fm_depth * kFmIndexMax;
        } else if (id == "detune2_semitones") {
            params_.detune2_semitones =
                std::min(std::max(value, kSemitoneMin), kSemitoneMax);
        } else if (id == "detune2_cents") {
            params_.detune2_cents = std::min(std::max(value, kCentsMin), kCentsMax);
        } else if (id == "master_gain") {
            params_.master_gain = std::min(std::max(value, 0.0), 1.5);
        } else if (id == "lpf_cutoff") {
            lpfCutoff_ = std::min(std::max(value, kLpfMinHz), kLpfMaxHz);
            updateLpf();
        } else if (id == "lpf_resonance") {
            lpfResonance_ = clampUnit(value);
            updateLpf();
        } else {
            return false;
        }
        return true;
    }

    bool setToggle(const std::string& id, bool value) {
        if (id == "osc1_square") {
            params_.osc1_square = value;
        } else if (id == "osc1_octave_down") {
            params_.osc1_octave_down = value;
        } else if (id == "osc2_octave_up") {
            params_.osc2_octave_up = value;
        } else {
            return false;
        }
        return true;
    }

    bool setChoice(const std::string& id, const std::string& value) {
        if (id == "mod_mode") {
            params_.mod_mode = parseMode(value);
        } else if (id == "lpf_mode") {
            params_.lpf_in_voice = value != "master";
        } else {
            return false;
        }
        return true;
    }

    // Render n frames of stereo float32, interleaved L/R.
    void render(float* interleaved, int n) {
        ensureBuffers(n);
        std::fill(mix_.begin(), mix_.begin() + n, 0.0);
        for (auto& v : voices_) {
            if (v.active()) {
                v.prepare(n);
                v.render(n, params_, mix_.data());
            }
        }
        if (!params_.lpf_in_voice && params_.lpf_active) {
            masterLpf_.process(mix_.data(), n, params_.lpf);
        }
        for (int i = 0; i < n; ++i) {
            const double y = std::tanh(mix_[i] * params_.master_gain);
            interleaved[2 * i] = static_cast<float>(y);
            interleaved[2 * i + 1] = static_cast<float>(y);
        }
    }

private:
    static double clampUnit(double v) { return std::min(std::max(v, 0.0), 1.0); }

    static Mode parseMode(const std::string& name) {
        if (name == "off") return Mode::kOff;
        if (name == "am") return Mode::kAm;
        if (name == "ring") return Mode::kRing;
        if (name == "sync") return Mode::kSync;
        return Mode::kFm;
    }

    Voice& allocate() {
        for (auto& v : voices_) {
            if (!v.active()) {
                return v;
            }
        }
        Voice* best = nullptr;
        for (auto& v : voices_) {
            if (v.gated()) {
                continue;
            }
            if (best == nullptr || v.envLevel() < best->envLevel() ||
                (v.envLevel() == best->envLevel() &&
                 v.triggerOrder() < best->triggerOrder())) {
                best = &v;
            }
        }
        if (best != nullptr) {
            return *best;
        }
        best = &voices_.front();
        for (auto& v : voices_) {
            if (v.triggerOrder() < best->triggerOrder()) {
                best = &v;
            }
        }
        return *best;
    }

    void updateLpf() {
        if (lpfCutoff_ >= kLpfMaxHz / 1.01) {
            params_.lpf_active = false;
        } else {
            params_.lpf_active = true;
            params_.lpf = lpfCoefficients(lpfCutoff_, lpfResonance_, sr_);
        }
    }

    void ensureBuffers(int n) {
        if (static_cast<int>(mix_.size()) < n) {
            mix_.resize(n);
        }
        prepare(n);
    }

    void prepare(int n) {
        for (auto& v : voices_) {
            v.prepare(n);
        }
        if (static_cast<int>(mix_.size()) < n) {
            mix_.resize(n);
        }
    }

    double sr_;
    int blockSize_;
    int maxVoices_;
    std::vector<Voice> voices_;
    Params params_;
    LowPass masterLpf_;
    std::vector<double> mix_;
    long order_ = 0;
    double lpfCutoff_ = kDefaultLpfCutoff;
    double lpfResonance_ = 0.0;
};

}  // namespace snakeoil
