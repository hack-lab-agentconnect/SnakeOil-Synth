#pragma once

#include <algorithm>

#include "snakeoil/constants.hpp"

namespace snakeoil {

// Linear ADSR, sample-exact with the Python Envelope.process: each sample is a
// repeated addition from the previous value (matching numpy cumsum), and stage
// changes land on the exact target value.
class Envelope {
public:
    enum Stage { kAttack = 0, kDecay = 1, kSustain = 2, kRelease = 3, kIdle = 4 };

    explicit Envelope(double sampleRate) : sr_(sampleRate) {
        setShape(kAmpAttack, kAmpDecay, kAmpSustain, kAmpRelease);
    }

    void setShape(double attack, double decay, double sustain, double release) {
        attack_ = std::max(attack, 1.0 / sr_);
        decay_ = std::max(decay, 1.0 / sr_);
        sustain_ = std::min(std::max(sustain, 0.0), 1.0);
        release_ = std::max(release, 1.0 / sr_);
    }

    void noteOn(bool keepLevel = false) {
        stage_ = kAttack;
        hasReleaseOverride_ = false;
        if (level_ >= 1.0 && !keepLevel) {
            level_ = 0.0;
        }
    }

    void noteOff(double releaseSeconds = -1.0) {
        if (stage_ != kIdle) {
            stage_ = kRelease;
            if (releaseSeconds >= 0.0) {
                releaseOverride_ = std::max(releaseSeconds, 1.0 / sr_);
                hasReleaseOverride_ = true;
            }
        }
    }

    bool active() const { return stage_ != kIdle; }
    double level() const { return level_; }
    int stage() const { return stage_; }
    void setIdle() { stage_ = kIdle; level_ = 0.0; }

    void process(double* out, int n) {
        const double attackInc = 1.0 / (attack_ * sr_);
        const double decayInc = (1.0 - sustain_) / (decay_ * sr_);
        const double releaseTime = hasReleaseOverride_ ? releaseOverride_ : release_;
        const double releaseInc = 1.0 / (releaseTime * sr_);
        double level = level_;
        int stage = stage_;
        const double sustain = sustain_;
        int pos = 0;
        while (pos < n) {
            const int remaining = n - pos;
            double inc = 0.0;
            double target = 0.0;
            int next = kIdle;
            bool hit = false;
            if (stage == kAttack) {
                inc = attackInc;
                target = 1.0;
                next = kDecay;
            } else if (stage == kDecay) {
                inc = -decayInc;
                target = sustain;
                next = kSustain;
            } else if (stage == kRelease) {
                inc = -releaseInc;
                target = 0.0;
                next = kIdle;
            } else {
                const double value = stage == kSustain ? sustain : level;
                for (int i = pos; i < n; ++i) {
                    out[i] = value;
                }
                if (stage == kSustain) {
                    level = sustain;
                }
                break;
            }
            int k = 0;
            double value = level;
            for (; k < remaining; ++k) {
                value += inc;
                if ((stage == kAttack && value >= target) ||
                    (stage != kAttack && value <= target)) {
                    hit = true;
                    break;
                }
                out[pos + k] = value;
            }
            if (hit) {
                out[pos + k] = target;
                level = target;
                stage = next;
                if (next == kIdle) {
                    hasReleaseOverride_ = false;
                }
                pos += k + 1;
            } else {
                level = value;
                pos = n;
            }
        }
        level_ = level;
        stage_ = stage;
    }

private:
    double sr_;
    double attack_ = kAmpAttack;
    double decay_ = kAmpDecay;
    double sustain_ = kAmpSustain;
    double release_ = kAmpRelease;
    double releaseOverride_ = 0.0;
    bool hasReleaseOverride_ = false;
    double level_ = 0.0;
    int stage_ = kIdle;
};

}  // namespace snakeoil
