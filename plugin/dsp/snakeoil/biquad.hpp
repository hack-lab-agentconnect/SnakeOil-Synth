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

struct BiquadPair {
    BiquadCoeffs a;
    BiquadCoeffs b;
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

inline BiquadCoeffs rbjSection(double w0, double q, double gain) {
    const double cosW0 = std::cos(w0);
    const double alpha = std::sin(w0) / (2.0 * q);
    const double a0 = 1.0 + alpha;
    const double b0 = gain * (1.0 - cosW0) / 2.0 / a0;
    return {b0, 2.0 * b0, b0, -2.0 * cosW0 / a0, (1.0 - alpha) / a0};
}

// Moog-style 4-pole low-pass as two cascaded RBJ sections, matching
// midi_synth.filters.lpf24_coefficients.
inline BiquadPair lpf24Coefficients(double cutoff, double resonance, double sr) {
    cutoff = std::min(std::max(cutoff, kLpfMinHz), 0.45 * sr);
    const double r = std::min(std::max(resonance, 0.0), 1.0);
    const double k = kLadderKMax * r;
    const double kappa = std::pow(k, 0.25);
    const double wc = 2.0 * sr * std::tan(kPi * cutoff / sr);
    const double c = std::sqrt(0.5) * kappa;
    const double wnA = wc * std::sqrt(1.0 - 2.0 * c + kappa * kappa);
    const double qA = wnA / (2.0 * wc * (1.0 - c));
    const double wnB = wc * std::sqrt(1.0 + 2.0 * c + kappa * kappa);
    const double qB = wnB / (2.0 * wc * (1.0 + c));
    return {rbjSection(2.0 * std::atan(wnA / (2.0 * sr)), qA, 1.0 / (1.0 + k)),
            rbjSection(2.0 * std::atan(wnB / (2.0 * sr)), qB, 1.0)};
}

// Direct-form II transposed biquad keeping state across blocks, matching
// scipy.signal.lfilter with a = [1, a1, a2]. A pair runs two cascaded.
class LowPass {
public:
    void reset() {
        z1_ = 0.0;
        z2_ = 0.0;
        z3_ = 0.0;
        z4_ = 0.0;
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

    void process(double* x, int n, const BiquadPair& c) {
        double z1 = z1_;
        double z2 = z2_;
        double z3 = z3_;
        double z4 = z4_;
        const BiquadCoeffs& a = c.a;
        const BiquadCoeffs& b = c.b;
        for (int i = 0; i < n; ++i) {
            const double xn = x[i];
            const double y1 = a.b0 * xn + z1;
            z1 = a.b1 * xn - a.a1 * y1 + z2;
            z2 = a.b2 * xn - a.a2 * y1;
            const double y2 = b.b0 * y1 + z3;
            z3 = b.b1 * y1 - b.a1 * y2 + z4;
            z4 = b.b2 * y1 - b.a2 * y2;
            x[i] = y2;
        }
        z1_ = z1;
        z2_ = z2;
        z3_ = z3;
        z4_ = z4;
    }

private:
    double z1_ = 0.0;
    double z2_ = 0.0;
    double z3_ = 0.0;
    double z4_ = 0.0;
};

}  // namespace snakeoil
