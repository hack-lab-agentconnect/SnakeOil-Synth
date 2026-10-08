#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <cstring>
#include <vector>

#include "snakeoil/biquad.hpp"
#include "snakeoil/envelope.hpp"
#include "snakeoil/oscillator.hpp"
#include "snakeoil/smoother.hpp"
#include "snakeoil/version.hpp"

TEST_CASE("version string is the expected semver") {
    const char* v = snakeoil::version();
    REQUIRE(v != nullptr);
    CHECK(std::strcmp(v, "0.1.0") == 0);
}

TEST_CASE("clamp bounds values") {
    CHECK(snakeoil::clamp(5.0, 0.0, 1.0) == 1.0);
    CHECK(snakeoil::clamp(-5.0, 0.0, 1.0) == 0.0);
    CHECK(snakeoil::clamp(0.25, 0.0, 1.0) == 0.25);
    CHECK(snakeoil::clamp(7, 1, 3) == 3);
}

TEST_CASE("smoother converges monotonically to its target") {
    snakeoil::Smoother s;
    s.setTime(0.01, 48000.0);
    s.reset(0.0);
    s.setTarget(1.0);
    double prev = 0.0;
    for (int i = 0; i < 48000; ++i) {
        const double v = s.next();
        REQUIRE(v >= prev);
        REQUIRE(v <= 1.0);
        prev = v;
    }
    CHECK(prev == doctest::Approx(1.0).epsilon(1e-9));
}

TEST_CASE("smoother with zero time jumps immediately") {
    snakeoil::Smoother s;
    s.setTime(0.0, 44100.0);
    s.reset(0.0);
    s.setTarget(0.5);
    CHECK(s.next() == 0.5);
}

TEST_CASE("osc 1 saw with square layer stays finite and bounded") {
    using namespace snakeoil;
    Oscillator osc(44100.0, false);
    osc.setLayerSquare(true);
    osc.setSquareLevel(kDefaultSquareLevel);
    osc.setDuty(kDefaultPwm);
    std::vector<double> out(2048);
    osc.generate(220.0, static_cast<int>(out.size()), out.data());
    double peak = 0.0;
    for (double v : out) {
        REQUIRE(std::isfinite(v));
        peak = std::max(peak, std::fabs(v));
    }
    CHECK(peak > 0.1);
    CHECK(peak < 2.5);  // saw + half a normalised pulse
}

TEST_CASE("envelope reaches full level and releases to idle") {
    using namespace snakeoil;
    Envelope env(44100.0);
    env.noteOn();
    std::vector<double> out(4096);
    env.process(out.data(), static_cast<int>(out.size()));
    double peak = 0.0;
    for (double v : out) {
        peak = std::max(peak, v);
    }
    CHECK(peak == doctest::Approx(1.0).epsilon(1e-6));
    env.setShape(0.0002, 0.0002, 0.5, 0.0002);
    env.noteOff();
    env.process(out.data(), static_cast<int>(out.size()));
    CHECK_FALSE(env.active());
    CHECK(env.level() == 0.0);
}

TEST_CASE("low-pass has unity DC gain") {
    using namespace snakeoil;
    const BiquadCoeffs c = lpfCoefficients(1000.0, 0.0, 44100.0);
    LowPass filter;
    std::vector<double> out(20000, 1.0);
    filter.process(out.data(), static_cast<int>(out.size()), c);
    CHECK(out.back() == doctest::Approx(1.0).epsilon(1e-3));
}
