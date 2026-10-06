#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstring>

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
