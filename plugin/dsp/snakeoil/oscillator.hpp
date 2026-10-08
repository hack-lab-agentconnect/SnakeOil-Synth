#pragma once

#include <algorithm>
#include <cmath>

#include "snakeoil/constants.hpp"

namespace snakeoil {

// numpy's np.mod(x, 1.0) for a scalar: fmod, then shift into [0, 1).
inline double mod1(double x) {
    const double r = std::fmod(x, 1.0);
    return r < 0.0 ? r + 1.0 : r;
}

// PolyBLEP correction with the same shape as the Python _poly_blep.
inline double polyBlep(double t, double dt) {
    const double d = dt > 1e-9 ? dt : 1e-9;
    const double a = std::max(1.0 - t / d, 0.0);
    const double b = std::max(1.0 + (t - 1.0) / d, 0.0);
    return b * b - a * a;
}

inline double sawWave(double t, double inc) {
    return 2.0 * t - 1.0 - polyBlep(t, inc);
}

inline double pulseFromEdges(double t, double duty, double rising, double inc) {
    double s = t < duty ? 1.0 : -1.0;
    s = s + rising - polyBlep(mod1(t - duty), inc);
    return (s - (2.0 * duty - 1.0)) / (2.0 - 2.0 * duty);
}

inline double pulseWave(double t, double inc, double duty) {
    const double d = std::min(std::max(duty, kMinDuty), 0.5);
    return pulseFromEdges(t, d, polyBlep(t, inc), inc);
}

// Juno-style top-aligned pulse used for oscillator 1's square layer: the saw
// ramp compared with a threshold, reusing the saw's blep for the falling edge.
inline double topPulse(double t, double inc, double duty, double blepT) {
    const double d = std::min(std::max(duty, kMinDuty), 0.5);
    double s = t >= 1.0 - d ? 1.0 : -1.0;
    s = s + polyBlep(mod1(t + d), inc) - blepT;
    return (s - (2.0 * d - 1.0)) / (2.0 - 2.0 * d);
}

// A single oscillator. Osc 1 is a saw (optionally layered with a square);
// osc 2 is a pulse. Phase advances from the block-start phase for every sample
// (never accumulatively) so the result matches numpy's vectorised version.
class Oscillator {
public:
    Oscillator(double sampleRate, bool isSquare) : sr_(sampleRate), square_(isSquare) {}

    void reset() { phase_ = 0.0; }

    bool isSquare() const { return square_; }
    void setLayerSquare(bool on) { layerSquare_ = on; }
    void setSquareLevel(double level) { squareLevel_ = level; }
    void setDuty(double duty) { duty_ = duty; }
    void setPhase(double phase) { phase_ = phase; }
    double phase() const { return phase_; }

    double shape(double t, double freq) const {
        const double inc = freq / sr_;
        if (!square_) {
            const double b0 = polyBlep(t, inc);
            const double saw = 2.0 * t - 1.0 - b0;
            if (layerSquare_ && squareLevel_ > 0.0) {
                return saw + squareLevel_ * topPulse(t, inc, duty_, b0);
            }
            return saw;
        }
        return pulseWave(t, inc, duty_);
    }

    // Fill ``out`` with the shaped wave and advance the phase. ``phaseMod`` (or
    // nullptr) is a per-sample phase offset in cycles, as in the FM path.
    void generate(double freq, int n, double* out, const double* phaseMod = nullptr) {
        const double inc = freq / sr_;
        const double start = phase_;
        for (int k = 0; k < n; ++k) {
            double t = mod1(start + inc * k);
            if (phaseMod != nullptr) {
                t = mod1(t + phaseMod[k]);
            }
            out[k] = shape(t, freq);
        }
        phase_ = mod1(start + inc * n);
    }

    // Advance the phase n samples without producing output (used when osc 2 is
    // inaudible but must keep its phase, exactly as the reference does).
    void advance(double freq, int n) {
        const double inc = freq / sr_;
        phase_ = mod1(phase_ + inc * n);
    }

    // Fill ``t`` with the raw phase and advance (used by hard sync).
    void advanceTo(double freq, int n, double* t) {
        const double inc = freq / sr_;
        const double start = phase_;
        for (int k = 0; k < n; ++k) {
            t[k] = mod1(start + inc * k);
        }
        phase_ = mod1(start + inc * n);
    }

private:
    double sr_;
    bool square_;
    bool layerSquare_ = false;
    double phase_ = 0.0;
    double duty_ = kDefaultDuty;
    double squareLevel_ = kDefaultSquareLevel;
};

}  // namespace snakeoil
