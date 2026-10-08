#pragma once

#include <algorithm>
#include <cmath>

#include "snakeoil/constants.hpp"

namespace snakeoil {

inline double resonanceToQ(double resonance) {
    const double r = std::min(std::max(resonance, 0.0), 1.0);
    return kQMin * std::pow(kQMax / kQMin, r);
}

struct BiquadCoeffs {
    double b0, b1, b2, a1, a2;
};

// RBJ low-pass, normalised, matching midi_synth.filters.lpf_coefficients.
inline BiquadCoeffs lpfCoefficients(double cutoff, double resonance, double sr) {
    cutoff = std::min(std::max(cutoff, kLpfMinHz), 0.45 * sr);
    const double w0 = 2.0 * kPi * cutoff / sr;
    const double cosW0 = std::cos(w0);
    const double alpha = std::sin(w0) / (2.0 * resonanceToQ(resonance));
    const double a0 = 1.0 + alpha;
    const double b0 = (1.0 - cosW0) / 2.0 / a0;
    return {b0, 2.0 * b0, b0, -2.0 * cosW0 / a0, (1.0 - alpha) / a0};
}

// Direct-form II transposed biquad keeping state across blocks, matching
// scipy.signal.lfilter with a = [1, a1, a2].
class LowPass {
public:
    void reset() {
        z1_ = 0.0;
        z2_ = 0.0;
    }

    void process(double* x, int n, const BiquadCoeffs& c) {
        double z1 = z1_;
        double z2 = z2_;
        for (int i = 0; i < n; ++i) {
            const double xn = x[i];
            const double yn = c.b0 * xn + z1;
            z1 = c.b1 * xn - c.a1 * yn + z2;
            z2 = c.b2 * xn - c.a2 * yn;
            x[i] = yn;
        }
        z1_ = z1;
        z2_ = z2;
    }

private:
    double z1_ = 0.0;
    double z2_ = 0.0;
};

}  // namespace snakeoil
