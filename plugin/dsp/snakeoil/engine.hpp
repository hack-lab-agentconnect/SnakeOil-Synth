#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <random>
#include <set>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

#include "snakeoil/biquad.hpp"
#include "snakeoil/constants.hpp"
#include "snakeoil/effects.hpp"
#include "snakeoil/limiter.hpp"
#include "snakeoil/lfo.hpp"
#include "snakeoil/mod_matrix.hpp"
#include "snakeoil/voice.hpp"

namespace snakeoil {

// Minimal engine for phase P1/P2: 12 classic voices, one low-pass, master gain
// and tanh. Parameters arrive by registry id (the same ids as
// midi_synth/params.py and plugin/params.json) and are stored generically; the
// ones the DSP understands are synced into Params once per block.
class Engine {
public:
    Engine(double sampleRate, int blockSize, int maxVoices = kMaxVoices,
           int tailSlots = 0, int tailCapacity = -1)
        : sr_(sampleRate), blockSize_(blockSize), maxVoices_(std::min(maxVoices, kMaxVoices)),
          effects_(sampleRate) {
        tailCapacity_ = std::max(tailCapacity < 0 ? tailSlots : tailCapacity, 0);
        tailSlots_ = std::min(std::max(tailSlots, 0), tailCapacity_);
        for (int i = 0; i < maxVoices_ + tailCapacity_; ++i) {
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
        const bool held = [this] {
            for (const auto& v : voices_) {
                if (v.gated()) return true;
            }
            return false;
        }();
        for (auto& v : voices_) {
            if (v.active() && v.note() == note && v.gated()) {
                v.noteOff();
            }
        }
        ++order_;
        const bool velocityOn = values_.at("velocity_on") >= 0.5;
        const double vel = velocityOn ? clampUnit(velocity / 127.0) : kFixedVelocity;
        const double glideTime = values_.at("glide_time");
        const bool legato = values_.at("glide_legato") >= 0.5;
        double glideFrom = -1.0;
        if (glideTime > 0.0 && hasLastFreq_ && (!legato || held)) {
            glideFrom = lastFreq_;
        }
        lastFreq_ = midiNoteToFreq(note);
        hasLastFreq_ = true;
        lastNote_ = note;
        const int count = unisonVoices();
        if (count <= 1) {
            Voice& voice = tailSlots_ > 0 ? allocateHybrid(1) : allocateClassic();
            voice.noteOn(note, vel, order_, voice.active(), glideFrom, glideTime,
                         nextNoiseStart());
        } else {
            noteOnUnison(note, vel, count, glideFrom, glideTime);
        }
    }

    int unisonVoices() const {
        auto it = choices_.find("unison_voices");
        if (it == choices_.end()) {
            return 1;
        }
        try {
            return std::min(std::max(std::stoi(it->second), 1), kMaxVoices);
        } catch (...) {
            return 1;
        }
    }

    std::vector<Voice*> allocateGroup(int count) {
        if (tailSlots_ > 0) {
            std::vector<Voice*> out;
            for (int i = 0; i < count; ++i) {
                out.push_back(&allocateHybrid(1));
            }
            return out;
        }
        std::vector<Voice*> chosen;
        for (auto& v : voices_) {
            if (!v.active() && static_cast<int>(chosen.size()) < count) {
                chosen.push_back(&v);
            }
        }
        if (static_cast<int>(chosen.size()) >= count) {
            return chosen;
        }
        // Steal whole groups, quietest/oldest first.
        std::vector<Voice*> activeVoices;
        for (auto& v : voices_) {
            if (v.active()) {
                activeVoices.push_back(&v);
            }
        }
        auto groups = voiceGroups(activeVoices, false);
        std::sort(groups.begin(), groups.end(),
                  [this](const std::vector<Voice*>& a, const std::vector<Voice*>& b) {
                      return victimKey(a) < victimKey(b);
                  });
        for (const auto& group : groups) {
            for (auto* v : group) {
                chosen.push_back(v);
            }
            if (static_cast<int>(chosen.size()) >= count) {
                break;
            }
        }
        return chosen;
    }

    void noteOnUnison(int note, double vel, int count, double glideFrom, double glideTime) {
        std::vector<Voice*> pool = allocateGroup(count);
        for (std::size_t i = static_cast<std::size_t>(count); i < pool.size(); ++i) {
            pool[i]->noteOff();
        }
        ++groupCounter_;
        const double detune = value("unison_detune", 15.0);
        const double spread = value("unison_spread", 0.5);
        const double gain = 1.0 / std::sqrt(static_cast<double>(count));
        for (int i = 0; i < count; ++i) {
            Voice* v = pool[static_cast<std::size_t>(i)];
            const double pos = count > 1 ? -1.0 + 2.0 * i / (count - 1) : 0.0;
            const bool stolen = v->active();
            const std::pair<double, double> phases = nextPhasePair();
            v->setGroup(groupCounter_);
            v->noteOn(note, vel, order_, stolen, glideFrom, glideTime, nextNoiseStart(),
                      pos * detune, pos * spread, gain, true, phases.first, phases.second);
        }
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

    // Noise tables (white/pink/brown) are injected: the golden harness loads the
    // exact tables exported from the Python reference, and the plugin embeds the
    // same data. Start positions are injected too when a scenario pins them,
    // otherwise a local RNG is used (noise is stochastic, so any stream is fine).
    void setNoiseTable(const std::string& color, std::vector<double> table) {
        noiseTables_[color] = std::move(table);
    }

    void setNoiseStarts(std::vector<long long> starts) {
        noiseStarts_ = std::move(starts);
        noiseStartIdx_ = 0;
    }

    long long nextNoiseStart() {
        if (noiseStartIdx_ < noiseStarts_.size()) {
            return noiseStarts_[noiseStartIdx_++];
        }
        std::uniform_int_distribution<long long> dist(0, 262143);
        return dist(noiseRng_);
    }

    // Unison random start phases, injected per scenario (two per voice) or drawn
    // from a local RNG in the plugin.
    void setUnisonPhases(std::vector<double> phases) {
        unisonPhases_ = std::move(phases);
        unisonPhaseIdx_ = 0;
    }

    std::pair<double, double> nextPhasePair() {
        if (unisonPhaseIdx_ + 1 < unisonPhases_.size()) {
            const double a = unisonPhases_[unisonPhaseIdx_++];
            const double b = unisonPhases_[unisonPhaseIdx_++];
            return {a, b};
        }
        std::uniform_real_distribution<double> dist(0.0, 1.0);
        return {dist(unisonRng_), dist(unisonRng_)};
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
        params_.lfo_pitch_ratio = 1.0;
        params_.lfo_filter_oct = 0.0;
        params_.lfo_pwm = 0.0;
        params_.lfo_amp = nullptr;
        if (lfoEnabled()) {
            if (static_cast<int>(lfoAmp_.size()) < n) {
                lfoAmp_.resize(n);
            }
            runLfo(n);
        }
        params_.mod_filter = false;
        applyMod();
        bool stereo = false;
        for (auto& v : voices_) {
            if (v.active() && v.pan() != 0.0) {
                stereo = true;
                break;
            }
        }
        if (stereo) {
            std::fill(left_.begin(), left_.begin() + n, 0.0);
            std::fill(right_.begin(), right_.begin() + n, 0.0);
            if (static_cast<int>(voiceOut_.size()) < n) {
                voiceOut_.resize(n);
            }
            for (auto& v : voices_) {
                if (v.active()) {
                    v.prepare(n);
                    std::fill(voiceOut_.begin(), voiceOut_.begin() + n, 0.0);
                    v.render(n, params_, voiceOut_.data());
                    const double pan = v.pan();
                    const double lg = 1.0 - std::max(0.0, pan);
                    const double rg = 1.0 + std::min(0.0, pan);
                    for (int k = 0; k < n; ++k) {
                        left_[k] += voiceOut_[k] * lg;
                        right_[k] += voiceOut_[k] * rg;
                    }
                }
            }
            if (!params_.lpf_in_voice && params_.lpf_active) {
                processMasterFilterStereo(n);
            }
        } else {
            std::fill(mix_.begin(), mix_.begin() + n, 0.0);
            for (auto& v : voices_) {
                if (v.active()) {
                    v.prepare(n);
                    v.render(n, params_, mix_.data());
                }
            }
            if (!params_.lpf_in_voice && params_.lpf_active) {
                processMasterFilter(n);
            }
            for (int i = 0; i < n; ++i) {
                left_[i] = mix_[i];
                right_[i] = mix_[i];
            }
        }
        if (effectsEnabled()) {
            effects_.process(left_.data(), right_.data(), n);
        }
        for (int i = 0; i < n; ++i) {
            left_[i] *= params_.master_gain;
            right_[i] *= params_.master_gain;
        }
        if (autoLimiter_) {
            const double peak = limiter_.process(left_.data(), right_.data(), n);
            if (peak < kLimiterSilenceThreshold) {
                limiterSilentS_ += n / sr_;
                if (limiterSilentS_ >= kLimiterSilenceS) {
                    limiter_.reset();
                    limiterSilentS_ = 0.0;
                }
            } else {
                limiterSilentS_ = 0.0;
            }
        }
        for (int i = 0; i < n; ++i) {
            const double l = std::tanh(left_[i]);
            const double r = std::tanh(right_[i]);
            interleaved[2 * i] = static_cast<float>(l);
            interleaved[2 * i + 1] = static_cast<float>(r);
            meterL_ = std::max(meterL_, std::fabs(l));
            meterR_ = std::max(meterR_, std::fabs(r));
            if (std::fabs(left_[i]) >= kClipThreshold || std::fabs(right_[i]) >= kClipThreshold) {
                meterClip_ = true;
            }
        }
    }

    // Post-clipper peaks and the clip flag since the last take, then reset.
    void takeMeter(double& left, double& right, bool& clipped) {
        left = meterL_;
        right = meterR_;
        clipped = meterClip_;
        meterL_ = 0.0;
        meterR_ = 0.0;
        meterClip_ = false;
    }

    void peekMeter(double& left, double& right, bool& clipped) const {
        left = meterL_;
        right = meterR_;
        clipped = meterClip_;
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
            {"glide_time", 0.0}, {"glide_legato", 0.0},
            {"lfo_depth", 0.0}, {"lfo2_depth", 0.0},
            {"fx_chorus", 0.0}, {"fx_chorus_depth", 0.3},
            {"fx_delay", 0.0}, {"fx_delay_time", 300.0}, {"fx_delay_pingpong", 0.0},
            {"fx_delay_feedback", 0.35}, {"fx_delay_damp", 0.25}, {"fx_delay_sync", 0.0},
            {"fx_reverb", 0.0}, {"fx_reverb_amount", 0.3},
            {"fx_reverb_size", 0.84}, {"fx_reverb_damp", 0.25},
            {"fx_bitcrush", 0.0}, {"fx_bitcrush_amount", 0.5},
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

        params_.amp_attack = std::max(num("amp_attack", kAmpAttack), 1.0 / sr_);
        params_.amp_decay = std::max(num("amp_decay", kAmpDecay), 1.0 / sr_);
        params_.amp_sustain = clampUnit(num("amp_sustain", kAmpSustain));
        params_.amp_release = std::max(num("amp_release", kAmpRelease), 1.0 / sr_);
        params_.flt_attack = std::max(num("flt_attack", kFltAttack), 1.0 / sr_);
        params_.flt_decay = std::max(num("flt_decay", kFltDecay), 1.0 / sr_);
        params_.flt_sustain = clampUnit(num("flt_sustain", kFltSustain));
        params_.flt_release = std::max(num("flt_release", kFltRelease), 1.0 / sr_);
        params_.flt_env_amount = std::min(std::max(num("flt_env_amount", 0.0), -1.0), 1.0);
        params_.flt_keytrack = clampUnit(num("flt_keytrack", 0.0));
        params_.flt_vel = clampUnit(num("flt_vel", 0.0));
        params_.noise_level = clampUnit(num("noise_level", 0.0));
        {
            auto table = noiseTables_.find(choice("noise_color", "white"));
            params_.noise_table = table == noiseTables_.end() ? nullptr : &table->second;
        }

        params_.lpf_in_voice = num("lpf_master", 0.0) < 0.5;
        params_.lpf_cutoff = std::min(std::max(num("lpf_cutoff", kDefaultLpfCutoff), kLpfMinHz), kLpfMaxHz);
        params_.lpf_resonance = clampUnit(num("lpf_resonance", 0.0));
        auto slopeIt = choices_.find("lpf_slope");
        params_.lpf_ladder = slopeIt != choices_.end() && slopeIt->second == "24 dB";
        if (params_.lpf_cutoff >= kLpfMaxHz / 1.01) {
            params_.lpf_active = false;
        } else {
            params_.lpf_active = true;
            if (params_.lpf_ladder) {
                params_.lpf24 = lpf24Coefficients(params_.lpf_cutoff, params_.lpf_resonance, sr_);
            } else {
                params_.lpf12 = lpfCoefficients(params_.lpf_cutoff, params_.lpf_resonance, sr_);
            }
        }
        auto modeIt = choices_.find("mod_mode");
        if (modeIt != choices_.end()) {
            params_.mod_mode = parseMode(modeIt->second);
        }
        const bool autoL = num("auto_limiter", 0.0) >= 0.5;
        if (autoL != autoLimiter_) {
            limiter_.reset();
            limiterSilentS_ = 0.0;
            autoLimiter_ = autoL;
        }
        syncEffects();
        syncMod();
    }

    double value(const std::string& id, double fallback = 0.0) const {
        auto it = values_.find(id);
        return it == values_.end() ? fallback : it->second;
    }

    void syncMod() {
        modRows_.clear();
        modLfo_[0] = modLfo_[1] = false;
        bool wheel = false;
        bool at = false;
        for (int slot = 1; slot <= 8; ++slot) {
            const std::string key = "mod" + std::to_string(slot);
            const std::string src = choice(key + "_src", "none");
            const std::string dst = choice(key + "_dst", "none");
            const double amt = value(key + "_amt", 0.0);
            if (src == "none" || dst == "none" || amt == 0.0) {
                continue;
            }
            const int si = sourceIndex(src);
            if (si == kSrcLfo1) modLfo_[0] = true;
            if (si == kSrcLfo2) modLfo_[1] = true;
            if (si == kSrcWheel) wheel = true;
            if (si == kSrcAftertouch) at = true;
            modRows_.push_back({si, amt, dst});
        }
        if (wheel && !wheelUsed_) {
            wheelS_ = modWheel_;
        }
        if (at && !atUsed_) {
            atS_ = aftertouch_;
        }
        wheelUsed_ = wheel;
        atUsed_ = at;
    }

    void applyMod() {
        if (modRows_.empty()) {
            return;
        }
        if (wheelUsed_) {
            wheelS_ = smoothStep(wheelS_, modWheel_);
        }
        if (atUsed_) {
            atS_ = smoothStep(atS_, aftertouch_);
        }
        const double src[6] = {0.0, 0.0, lfoLast_[0], lfoLast_[1], wheelS_, atS_};
        int destCount = 0;
        const ModDest* dests = modDestinations(destCount);
        for (const auto& row : modRows_) {
            const ModDest* dest = nullptr;
            for (int i = 0; i < destCount; ++i) {
                if (row.dst == dests[i].name) {
                    dest = &dests[i];
                    break;
                }
            }
            if (dest == nullptr) {
                continue;
            }
            const double base = value(dest->paramId, 0.0);
            const double eff = effective(base, row.amt * src[row.src], dest->lo, dest->hi);
            applyModDest(*dest, eff);
        }
    }

    void applyModDest(const ModDest& d, double eff) {
        const std::string id = d.paramId;
        if (d.fx) {
            if (id == "fx_chorus_depth") effects_.chorus().setDepth(eff);
            else if (id == "fx_delay_time") effects_.delay().setTimeMs(eff);
            else if (id == "fx_delay_feedback") effects_.delay().setFeedback(eff);
            else if (id == "fx_delay_damp") effects_.delay().setDamp(eff);
            else if (id == "fx_reverb_amount") effects_.reverb().setAmount(eff);
            else if (id == "fx_reverb_size") effects_.reverb().setRoom(eff);
            else if (id == "fx_reverb_damp") effects_.reverb().setDamp(eff);
            else if (id == "fx_bitcrush_amount") effects_.bitcrush().setAmount(eff);
            return;
        }
        if (id == "lpf_cutoff") { params_.lpf_cutoff = eff; params_.mod_filter = true; }
        else if (id == "lpf_resonance") { params_.lpf_resonance = eff; params_.mod_filter = true; }
        else if (id == "fm_depth") { params_.fm_depth = eff; params_.mod_index = eff * kFmIndexMax; }
        else if (id == "osc1_level") params_.osc1_level = eff;
        else if (id == "osc1_pwm") params_.osc1_pwm = eff;
        else if (id == "osc1_square_level") params_.osc1_square_level = eff;
        else if (id == "osc2_level") params_.osc2_level = eff;
        else if (id == "detune2_semitones") params_.detune2_semitones = eff;
        else if (id == "detune2_cents") params_.detune2_cents = eff;
        else if (id == "osc2_pwm") params_.osc2_pwm = eff;
        else if (id == "amp_attack") params_.amp_attack = eff;
        else if (id == "amp_decay") params_.amp_decay = eff;
        else if (id == "amp_sustain") params_.amp_sustain = eff;
        else if (id == "amp_release") params_.amp_release = eff;
        else if (id == "flt_attack") params_.flt_attack = eff;
        else if (id == "flt_decay") params_.flt_decay = eff;
        else if (id == "flt_sustain") params_.flt_sustain = eff;
        else if (id == "flt_release") params_.flt_release = eff;
        else if (id == "flt_env_amount") params_.flt_env_amount = eff;
        else if (id == "flt_keytrack") params_.flt_keytrack = eff;
        else if (id == "flt_vel") params_.flt_vel = eff;
    }

    std::string choice(const std::string& id, const std::string& fallback) const {
        auto it = choices_.find(id);
        return it == choices_.end() ? fallback : it->second;
    }

    void syncEffects() {
        const auto num = [this](const char* id, double fallback) {
            auto it = values_.find(id);
            return it == values_.end() ? fallback : it->second;
        };
        effects_.chorus().setEnabled(num("fx_chorus", 0.0) >= 0.5);
        effects_.chorus().setDepth(num("fx_chorus_depth", 0.3));
        effects_.delay().setEnabled(num("fx_delay", 0.0) >= 0.5);
        double delayMs = num("fx_delay_time", 300.0);
        if (num("fx_delay_sync", 0.0) >= 0.5) {
            const double bpm = effectiveBpm();
            delayMs = 60000.0 / bpm * divisionBeats(choice("fx_delay_division", "1/8"));
            delayMs = std::min(std::max(delayMs, 1.0), 4000.0);
        }
        effects_.delay().setTimeMs(delayMs);
        effects_.delay().setPingpong(num("fx_delay_pingpong", 0.0) >= 0.5);
        effects_.delay().setFeedback(num("fx_delay_feedback", 0.35));
        effects_.delay().setDamp(num("fx_delay_damp", 0.25));
        effects_.reverb().setEnabled(num("fx_reverb", 0.0) >= 0.5);
        effects_.reverb().setAmount(num("fx_reverb_amount", 0.3));
        effects_.reverb().setRoom(num("fx_reverb_size", 0.84));
        effects_.reverb().setDamp(num("fx_reverb_damp", 0.25));
        effects_.bitcrush().setEnabled(num("fx_bitcrush", 0.0) >= 0.5);
        effects_.bitcrush().setAmount(num("fx_bitcrush_amount", 0.5));
    }

    bool effectsEnabled() const {
        const auto get = [this](const char* id) {
            auto it = values_.find(id);
            return it == values_.end() ? 0.0 : it->second;
        };
        return get("fx_chorus") >= 0.5 || get("fx_delay") >= 0.5 ||
               get("fx_reverb") >= 0.5 || get("fx_bitcrush") >= 0.5;
    }

    // The tempo driving a synced delay: the host tempo when the wrapper
    // supplies one, else the manual tempo_bpm.
    double effectiveBpm() const {
        double bpm = hasHostTempo_ ? hostTempo_ : value("tempo_bpm", 120.0);
        return std::min(std::max(bpm, 40.0), 240.0);
    }

    void setHostTempo(double bpm, bool valid) {
        hostTempo_ = bpm;
        hasHostTempo_ = valid;
    }

    static double divisionBeats(const std::string& name) {
        if (name == "1/1") return 4.0;
        if (name == "1/2") return 2.0;
        if (name == "1/2.") return 3.0;
        if (name == "1/4") return 1.0;
        if (name == "1/4.") return 1.5;
        if (name == "1/4T") return 2.0 / 3.0;
        if (name == "1/8") return 0.5;
        if (name == "1/8.") return 0.75;
        if (name == "1/8T") return 1.0 / 3.0;
        if (name == "1/16") return 0.25;
        if (name == "1/16.") return 0.375;
        return 0.5;
    }

    static Mode parseMode(const std::string& name) {
        if (name == "off") return Mode::kOff;
        if (name == "am") return Mode::kAm;
        if (name == "ring") return Mode::kRing;
        if (name == "sync") return Mode::kSync;
        return Mode::kFm;
    }

    bool lfoEnabled() const {
        const auto get = [this](const char* id) {
            auto it = values_.find(id);
            return it == values_.end() ? 0.0 : it->second;
        };
        return clampUnit(get("lfo_depth")) > 0.0 || clampUnit(get("lfo2_depth")) > 0.0 ||
               modLfo_[0] || modLfo_[1];
    }

    void runLfo(int n) {
        const auto num = [this](const std::string& id, double fallback) {
            auto it = values_.find(id);
            return it == values_.end() ? fallback : it->second;
        };
        const auto cho = [this](const std::string& id, const std::string& fallback) {
            auto it = choices_.find(id);
            return it == choices_.end() ? fallback : it->second;
        };
        const char* pre[2] = {"lfo", "lfo2"};
        const char* cross[2] = {"lfo2-rate", "lfo1-rate"};
        LFO* lfos[2] = {&lfo1_, &lfo2_};
        double depth[2] = {clampUnit(num("lfo_depth", 0.0)),
                           clampUnit(num("lfo2_depth", 0.0))};
        std::set<std::string> seen;
        double cur[2] = {0.0, 0.0};
        bool ampActive = false;
        for (int i = 0; i < 2; ++i) {
            const bool routed = depth[i] > 0.0;
            double rate = num(std::string(pre[i]) + "_rate", kDefaultLfoRate);
            if (!routed && !modLfo_[i]) {
                lfoRateEff_[i] = rate;
                continue;
            }
            const std::string dest = cho(std::string(pre[i]) + "_dest", i == 0 ? "pitch" : "filter");
            const int o = 1 - i;
            if (depth[o] > 0.0 && cho(std::string(pre[o]) + "_dest", "") == cross[o]) {
                rate *= std::pow(2.0, depth[o] * lfoLast_[o] * kLfoRateModOctaves);
                rate = std::min(std::max(rate, kLfoRateFloor), kLfoRateCeil);
            }
            lfoRateEff_[i] = rate;
            const bool wantArray = routed && dest == "amp";
            const double mid = lfos[i]->nextBlock(
                n, sr_, rate, cho(std::string(pre[i]) + "_wave", "sine"),
                wantArray ? lfoAmp_.data() : nullptr);
            cur[i] = mid;
            if (!routed) {
                continue;
            }
            const bool first = seen.insert(dest).second;
            if (dest == "pitch") {
                const double ratio = std::pow(2.0, depth[i] * kLfoPitchSemitones * mid / 12.0);
                params_.lfo_pitch_ratio = first ? ratio : params_.lfo_pitch_ratio * ratio;
            } else if (dest == "filter") {
                const double octs = depth[i] * kLfoFilterOctaves * mid;
                params_.lfo_filter_oct = first ? octs : params_.lfo_filter_oct + octs;
            } else if (dest == "pwm") {
                const double off = depth[i] * kLfoPwmRange * mid;
                params_.lfo_pwm = first ? off : params_.lfo_pwm + off;
            } else if (dest == "amp") {
                for (int k = 0; k < n; ++k) {
                    const double gain = 1.0 - depth[i] * (0.5 - 0.5 * lfoAmp_[k]);
                    lfoAmp_[k] = ampActive ? lfoAmp_[k] * gain : gain;
                }
                ampActive = true;
            }
        }
        lfoLast_[0] = cur[0];
        lfoLast_[1] = cur[1];
        params_.lfo_amp = ampActive ? lfoAmp_.data() : nullptr;
    }

    void processMasterFilter(int n) {
        if (params_.lfo_filter_oct != 0.0) {
            double cutoff = params_.lpf_cutoff * std::pow(2.0, params_.lfo_filter_oct);
            cutoff = std::min(std::max(cutoff, kLpfMinHz), 0.45 * sr_);
            if (cutoff >= kLpfMaxHz / 1.01) {
                if (!masterBypassed_) {
                    masterLpf_.reset();
                    masterBypassed_ = true;
                }
                return;
            }
            if (masterBypassed_) {
                masterLpf_.reset();
                masterBypassed_ = false;
            }
            if (params_.lpf_ladder) {
                masterLpf_.process(mix_.data(), n,
                                   lpf24Coefficients(cutoff, params_.lpf_resonance, sr_));
            } else {
                masterLpf_.process(mix_.data(), n,
                                   lpfCoefficients(cutoff, params_.lpf_resonance, sr_));
            }
            return;
        }
        if (params_.lpf_ladder) {
            masterLpf_.process(mix_.data(), n, params_.lpf24);
        } else {
            masterLpf_.process(mix_.data(), n, params_.lpf12);
        }
    }

    void processMasterFilterStereo(int n) {
        if (params_.lfo_filter_oct != 0.0) {
            double cutoff = params_.lpf_cutoff * std::pow(2.0, params_.lfo_filter_oct);
            cutoff = std::min(std::max(cutoff, kLpfMinHz), 0.45 * sr_);
            if (cutoff >= kLpfMaxHz / 1.01) {
                masterLpf_.reset();
                masterLpfR_.reset();
                return;
            }
            if (params_.lpf_ladder) {
                const BiquadPair c = lpf24Coefficients(cutoff, params_.lpf_resonance, sr_);
                masterLpf_.process(left_.data(), n, c);
                masterLpfR_.process(right_.data(), n, c);
            } else {
                const BiquadCoeffs c = lpfCoefficients(cutoff, params_.lpf_resonance, sr_);
                masterLpf_.process(left_.data(), n, c);
                masterLpfR_.process(right_.data(), n, c);
            }
            return;
        }
        if (params_.lpf_ladder) {
            masterLpf_.process(left_.data(), n, params_.lpf24);
            masterLpfR_.process(right_.data(), n, params_.lpf24);
        } else {
            masterLpf_.process(left_.data(), n, params_.lpf12);
            masterLpfR_.process(right_.data(), n, params_.lpf12);
        }
    }

    Voice& allocateClassic() {
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

    using VictimKey = std::tuple<int, double, long>;

    VictimKey victimKey(const std::vector<Voice*>& group) const {
        long oldest = group.front()->triggerOrder();
        bool anyGate = false;
        double sum = 0.0;
        for (auto* v : group) {
            oldest = std::min(oldest, v->triggerOrder());
            anyGate = anyGate || v->gated();
            sum += v->envLevel();
        }
        if (anyGate) {
            return VictimKey(1, 0.0, oldest);
        }
        return VictimKey(0, sum, oldest);
    }

    std::vector<std::vector<Voice*>> voiceGroups(const std::vector<Voice*>& voices,
                                                 bool perVoice) const {
        std::vector<std::vector<Voice*>> groups;
        std::vector<int> keys;
        for (auto* v : voices) {
            const int key = (perVoice || v->groupId() < 0)
                                ? 1000000 + static_cast<int>(v - voices_.data())
                                : v->groupId();
            int pos = -1;
            for (std::size_t i = 0; i < keys.size(); ++i) {
                if (keys[i] == key) {
                    pos = static_cast<int>(i);
                    break;
                }
            }
            if (pos < 0) {
                keys.push_back(key);
                groups.emplace_back();
                pos = static_cast<int>(groups.size()) - 1;
            }
            groups[static_cast<std::size_t>(pos)].push_back(v);
        }
        return groups;
    }

    std::vector<Voice*> forceReleaseFor(int count) {
        std::vector<Voice*> forced;
        while (true) {
            std::vector<Voice*> held;
            for (auto& v : voices_) {
                if (v.gated()) {
                    held.push_back(&v);
                }
            }
            if (static_cast<int>(held.size()) + count <= maxVoices_ || held.empty()) {
                return forced;
            }
            auto groups = voiceGroups(held, false);
            std::size_t oldest = 0;
            long oldestOrder = groups.front().front()->triggerOrder();
            for (std::size_t i = 0; i < groups.size(); ++i) {
                long order = groups[i].front()->triggerOrder();
                for (auto* v : groups[i]) {
                    order = std::min(order, v->triggerOrder());
                }
                if (order < oldestOrder) {
                    oldestOrder = order;
                    oldest = i;
                }
            }
            for (auto* v : groups[oldest]) {
                v->forceRelease(kForcedReleaseS);
                forced.push_back(v);
            }
        }
    }

    Voice& allocateHybrid(int count) {
        const std::vector<Voice*> forced = forceReleaseFor(count);
        int active = 0;
        for (auto& v : voices_) {
            if (v.active()) {
                ++active;
            }
        }
        const int room = std::max(maxVoices_ + tailSlots_ - active, 0);
        std::vector<Voice*> chosen;
        for (auto& v : voices_) {
            if (!v.active() && static_cast<int>(chosen.size()) < std::min(room, count)) {
                chosen.push_back(&v);
            }
        }
        if (static_cast<int>(chosen.size()) >= count) {
            return *chosen.front();
        }
        std::set<Voice*> skip(forced.begin(), forced.end());
        const bool perVoice = count == 1;
        auto victims = [&](const std::function<bool(Voice*)>& pred) {
            std::vector<Voice*> cands;
            for (auto& v : voices_) {
                if (v.active() && pred(&v)) {
                    cands.push_back(&v);
                }
            }
            auto groups = voiceGroups(cands, perVoice);
            std::sort(groups.begin(), groups.end(),
                      [this](const std::vector<Voice*>& a, const std::vector<Voice*>& b) {
                          return victimKey(a) < victimKey(b);
                      });
            return groups;
        };
        const std::vector<std::vector<Voice*>> tiers[3] = {
            victims([&](Voice* v) { return !v->gated() && skip.count(v) == 0; }),
            victims([&](Voice* v) { return skip.count(v) > 0; }),
            victims([&](Voice* v) { return v->gated(); }),
        };
        for (const auto& tier : tiers) {
            for (const auto& group : tier) {
                for (auto* v : group) {
                    chosen.push_back(v);
                }
                if (static_cast<int>(chosen.size()) >= count) {
                    return *chosen.front();
                }
            }
        }
        return chosen.empty() ? voices_.front() : *chosen.front();
    }

    void ensureBuffers(int n) {
        if (static_cast<int>(mix_.size()) < n) {
            mix_.resize(n);
        }
        if (static_cast<int>(left_.size()) < n) {
            left_.resize(n);
        }
        if (static_cast<int>(right_.size()) < n) {
            right_.resize(n);
        }
        if (static_cast<int>(voiceOut_.size()) < n) {
            voiceOut_.resize(n);
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

    struct ModRow {
        int src;
        double amt;
        std::string dst;
    };

    double sr_;
    int blockSize_;
    int maxVoices_;
    int tailSlots_ = 0;
    int tailCapacity_ = 0;
    std::vector<Voice> voices_;
    Params params_;
    LowPass masterLpf_;
    EffectChain effects_;
    std::vector<double> mix_;
    std::vector<double> left_;
    std::vector<double> right_;
    std::vector<double> voiceOut_;
    LowPass masterLpfR_;
    Limiter limiter_;
    bool autoLimiter_ = false;
    double limiterSilentS_ = 0.0;
    LFO lfo1_;
    LFO lfo2_;
    double lfoLast_[2] = {0.0, 0.0};
    double lfoRateEff_[2] = {kDefaultLfoRate, kDefaultLfoRate};
    std::vector<double> lfoAmp_;
    bool modLfo_[2] = {false, false};
    bool masterBypassed_ = false;
    std::vector<ModRow> modRows_;
    bool wheelUsed_ = false;
    bool atUsed_ = false;
    double wheelS_ = 0.0;
    double atS_ = 0.0;
    int lastNote_ = -1;
    double meterL_ = 0.0;
    double meterR_ = 0.0;
    bool meterClip_ = false;
    double hostTempo_ = 120.0;
    bool hasHostTempo_ = false;
    std::unordered_map<std::string, std::vector<double>> noiseTables_;
    std::vector<long long> noiseStarts_;
    std::size_t noiseStartIdx_ = 0;
    std::mt19937 noiseRng_{std::random_device{}()};
    std::vector<double> unisonPhases_;
    std::size_t unisonPhaseIdx_ = 0;
    std::mt19937 unisonRng_{std::random_device{}()};
    long groupCounter_ = 0;
    std::unordered_map<std::string, double> values_;
    std::unordered_map<std::string, std::string> choices_;
    std::set<int> sustained_;
    bool sustain_ = false;
    double pitchBend_ = 0.0;
    double modWheel_ = 0.0;
    double aftertouch_ = 0.0;
    bool hasLastFreq_ = false;
    double lastFreq_ = 0.0;
    long order_ = 0;
};

}  // namespace snakeoil
