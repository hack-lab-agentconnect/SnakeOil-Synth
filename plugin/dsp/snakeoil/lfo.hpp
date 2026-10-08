#pragma once

#include <algorithm>
#include <cmath>
#include <string>

#include "snakeoil/constants.hpp"
#include "snakeoil/oscillator.hpp"

namespace snakeoil {

// Low-frequency oscillator advanced once per block, matching
// midi_synth/lfo.py for the deterministic waveforms. The random and
// random-glide waves need numpy's seeded RNG and are not implemented yet
// (they return 0).
inline double lfoShape(const std::string& wave, double phase) {
    if (wave == "sine") {
        return std::sin(2.0 * kPi * phase);
    }
    if (wave == "triangle") {
        return 1.0 - 4.0 * std::fabs(mod1(phase + 0.25) - 0.5);
    }
    if (wave == "saw") {
        return 2.0 * phase - 1.0;
    }
    if (wave == "square") {
        return phase < 0.5 ? 1.0 : -1.0;
    }
    return 0.0;
}

class LFO {
public:
    void reset() { phase_ = 0.0; }

    // Returns the block-centre value; when ``samples`` is non-null it is filled
    // with the per-sample values.
    double nextBlock(int n, double sr, double rate, const std::string& wave,
                     double* samples) {
        const double start = phase_;
        const double inc = rate * n / sr;
        const double midPhase = start + 0.5 * inc;
        if (samples != nullptr) {
            for (int k = 0; k < n; ++k) {
                const double phase = mod1(start + inc * k / n);
                samples[k] = lfoShape(wave, phase);
            }
        }
        const double mid = lfoShape(wave, mod1(midPhase));
        phase_ = mod1(start + inc);
        return mid;
    }

private:
    double phase_ = 0.0;
};

}  // namespace snakeoil
