#pragma once

#include <algorithm>
#include <cmath>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

#include "snakeoil/biquad.hpp"
#include "snakeoil/constants.hpp"
#include "snakeoil/voice.hpp"

namespace snakeoil {

// Minimal engine for phase P1/P2: 12 classic voices, one low-pass, master gain
// and tanh. Parameters arrive by registry id (the same ids as
// midi_synth/params.py and plugin/params.json) and are stored generically; the
// ones the DSP understands are synced into Params once per block.
class Engine {
public:
    Engine(double sampleRate, int blockSize, int maxVoices = kMaxVoices)
        : sr_(sampleRate), blockSize_(blockSize), maxVoices_(std::min(maxVoices, kMaxVoices)) {
        for (int i = 0; i < maxVoices_; ++i) {
            voices_.emplace_back(sampleRate);
        }
        prepare(blockSize);
        loadDefaults();
        syncHotParams();
    }

    Params& params() { return params_; }
    const Params& params() const { return params_; }
    double sampleRate() const { return sr_; }
    int blockSize() const { return blockSize_; }

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
        const bool velocityOn = values_.at("velocity_on") >= 0.5;
        const double vel = velocityOn ? clampUnit(velocity / 127.0) : kFixedVelocity;
        Voice& voice = allocate();
        voice.noteOn(note, vel, order_, voice.active());
    }

    void noteOff(int note) {
        if (sustain_) {
            sustained_.insert(note);
            return;
        }
        for (auto& v : voices_) {
            if (v.note() == note && v.gated()) {
                v.noteOff();
            }
        }
    }

    void allNotesOff() {
        sustained_.clear();
        for (auto& v : voices_) {
            if (v.active()) {
                v.noteOff();
            }
        }
    }

    void setSustain(bool on) {
        sustain_ = on;
        if (!on) {
            for (auto& v : voices_) {
                if (v.gated() && sustained_.count(v.note()) > 0) {
                    v.noteOff();
                }
            }
            sustained_.clear();
        }
    }

    void setPitchBend(double normalized) {
        pitchBend_ = normalized * kPitchBendRange;
        params_.pitch_ratio = std::pow(2.0, pitchBend_ / 12.0);
    }

    void setModWheel(double value) { modWheel_ = clampUnit(value); }
    void setAftertouch(double value) { aftertouch_ = clampUnit(value); }

    void resetControllers() {
        setPitchBend(0.0);
        setSustain(false);
        modWheel_ = 0.0;
        aftertouch_ = 0.0;
    }

    // --- parameter interface (ids match the Python registry) ---------------

    bool setParamById(const std::string& id, double value) {
        values_[id] = value;
        return true;
    }

    bool setChoice(const std::string& id, const std::string& value) {
        choices_[id] = value;
        return true;
    }

    double getParamById(const std::string& id) const {
        auto it = values_.find(id);
        return it == values_.end() ? 0.0 : it->second;
    }

    std::string getChoice(const std::string& id) const {
        auto it = choices_.find(id);
        return it == choices_.end() ? std::string() : it->second;
    }

    // Render n frames of stereo float32, interleaved L/R.
    void render(float* interleaved, int n) {
        syncHotParams();
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

    void loadDefaults() {
        // Defaults mirror midi_synth/config.py and the registry defaults.
        values_ = {
            {"osc1_level", 1.0}, {"osc1_square", 1.0}, {"osc1_square_level", 0.5},
            {"osc1_pwm", 0.0}, {"osc1_octave", 0.0},
            {"osc2_level", 0.0}, {"detune2_semitones", 0.0}, {"detune2_cents", 0.0},
            {"osc2_pwm", 0.0}, {"osc2_octave", 1.0},
            {"fm_depth", 0.0},
            {"lpf_cutoff", kDefaultLpfCutoff}, {"lpf_resonance", 0.0},
            {"lpf_master", 0.0},
            {"master_gain", kDefaultMasterGain},
            {"velocity_on", 1.0}, {"auto_limiter", 0.0},
            {"amp_attack", kAmpAttack}, {"amp_decay", kAmpDecay},
            {"amp_sustain", kAmpSustain}, {"amp_release", kAmpRelease},
        };
        choices_ = {
            {"mod_mode", "fm"}, {"lpf_slope", "12 dB"},
        };
    }

    void syncHotParams() {
        const auto num = [this](const char* id, double fallback) {
            auto it = values_.find(id);
            return it == values_.end() ? fallback : it->second;
        };
        params_.osc1_level = clampUnit(num("osc1_level", 1.0));
        params_.osc2_level = clampUnit(num("osc2_level", 0.0));
        params_.osc1_square = num("osc1_square", 1.0) >= 0.5;
        params_.osc1_square_level = clampUnit(num("osc1_square_level", 0.5));
        params_.osc1_pwm = std::min(std::max(num("osc1_pwm", 0.0), 0.0), 0.5);
        params_.osc2_pwm = std::min(std::max(num("osc2_pwm", 0.0), 0.0), 0.5);
        params_.osc1_octave_down = num("osc1_octave", 0.0) >= 0.5;
        params_.osc2_octave_up = num("osc2_octave", 1.0) >= 0.5;
        params_.detune2_semitones =
            std::min(std::max(num("detune2_semitones", 0.0), kSemitoneMin), kSemitoneMax);
        params_.detune2_cents =
            std::min(std::max(num("detune2_cents", 0.0), kCentsMin), kCentsMax);
        params_.fm_depth = clampUnit(num("fm_depth", 0.0));
        params_.mod_index = params_.fm_depth * kFmIndexMax;
        params_.master_gain = std::min(std::max(num("master_gain", kDefaultMasterGain), 0.0), 1.5);
        params_.lpf_in_voice = num("lpf_master", 0.0) < 0.5;
        const double cutoff = std::min(std::max(num("lpf_cutoff", kDefaultLpfCutoff), kLpfMinHz), kLpfMaxHz);
        const double resonance = clampUnit(num("lpf_resonance", 0.0));
        if (cutoff >= kLpfMaxHz / 1.01) {
            params_.lpf_active = false;
        } else {
            params_.lpf_active = true;
            params_.lpf = lpfCoefficients(cutoff, resonance, sr_);
        }
        auto modeIt = choices_.find("mod_mode");
        if (modeIt != choices_.end()) {
            params_.mod_mode = parseMode(modeIt->second);
        }
    }

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
    std::unordered_map<std::string, double> values_;
    std::unordered_map<std::string, std::string> choices_;
    std::set<int> sustained_;
    bool sustain_ = false;
    double pitchBend_ = 0.0;
    double modWheel_ = 0.0;
    double aftertouch_ = 0.0;
    long order_ = 0;
};

}  // namespace snakeoil
