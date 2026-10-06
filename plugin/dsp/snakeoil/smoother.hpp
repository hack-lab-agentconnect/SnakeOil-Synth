#pragma once

#include <cmath>

namespace snakeoil {

template <typename T>
constexpr T clamp(T value, T lo, T hi) noexcept {
    return value < lo ? lo : (value > hi ? hi : value);
}

// One-pole parameter smoother. Real-time safe: no allocation, no locks.
class Smoother {
public:
    // Reach ~63% of a step after timeSeconds.
    void setTime(double timeSeconds, double sampleRate) noexcept {
        coeff_ = timeSeconds <= 0.0 ? 1.0 : 1.0 - std::exp(-1.0 / (timeSeconds * sampleRate));
    }
    void reset(double value) noexcept { current_ = target_ = value; }
    void setTarget(double value) noexcept { target_ = value; }
    double next() noexcept {
        current_ += (target_ - current_) * coeff_;
        return current_;
    }
    double current() const noexcept { return current_; }

private:
    double current_ = 0.0;
    double target_ = 0.0;
    double coeff_ = 1.0;
};

}  // namespace snakeoil
