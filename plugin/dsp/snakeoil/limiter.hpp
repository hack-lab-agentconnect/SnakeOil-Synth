#pragma once

#include <algorithm>
#include <cmath>

#include "snakeoil/constants.hpp"

namespace snakeoil {

// Auto limiter: stereo-linked, instant attack, holds its gain reduction until
// reset. Matches midi_synth/limiter.py.
class Limiter {
public:
    void reset() { h_ = 0.0; }
    double heldReduction() const { return h_; }

    // Limit the stereo pair in place; returns the input block peak.
    double process(double* left, double* right, int n) {
        double blockPeak = 0.0;
        for (int i = 0; i < n; ++i) {
            const double peak = std::max(std::fabs(left[i]), std::fabs(right[i]));
            blockPeak = std::max(blockPeak, peak);
        }
        if (h_ == 0.0 && !(blockPeak > kLimiterCeiling)) {
            return blockPeak;
        }
        double h = h_;
        for (int i = 0; i < n; ++i) {
            const double peak = std::max(std::fabs(left[i]), std::fabs(right[i]));
            double a = 1.0 - kLimiterCeiling / std::max(peak, kLimiterCeiling);
            a = std::min(a, 1.0);
            h = std::max(h, a);
            left[i] *= (1.0 - h);
            right[i] *= (1.0 - h);
        }
        h_ = h;
        return blockPeak;
    }

private:
    double h_ = 0.0;
};

}  // namespace snakeoil
