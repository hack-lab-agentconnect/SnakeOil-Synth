#pragma once

// Constants shared with the Python reference (midi_synth/config.py). Keep the
// values and names in step with that file; the golden harness guards the
// behaviour, not these numbers.

namespace snakeoil {

constexpr double kPi = 3.14159265358979323846;

constexpr int kMaxVoices = 12;

// Upper bound on the audio block size the DSP processes in one call. Hosts
// rarely exceed this; the JUCE wrapper clamps its block size to it.
constexpr int kMaxBlock = 8192;

constexpr double kMinDuty = 0.02;
constexpr double kDefaultDuty = 0.5;
constexpr double kDefaultPwm = 0.0;
constexpr double kDefaultSquareLevel = 0.5;

constexpr double kFmIndexMax = 8.0;
constexpr double kPitchBendRange = 2.0;

constexpr double kDefaultModeDepth = 0.7;
constexpr double kSemitoneMin = -12.0;
constexpr double kSemitoneMax = 12.0;
constexpr double kCentsMin = -0.5;
constexpr double kCentsMax = 0.5;

constexpr double kLpfMinHz = 20.0;
constexpr double kLpfMaxHz = 20000.0;
constexpr double kQMin = 0.707;
constexpr double kQMax = 12.0;
constexpr double kDefaultLpfCutoff = 2000.0;

constexpr double kAmpAttack = 0.006;
constexpr double kAmpDecay = 0.120;
constexpr double kAmpSustain = 0.75;
constexpr double kAmpRelease = 0.180;

constexpr double kFltAttack = 0.005;
constexpr double kFltDecay = 0.3;
constexpr double kFltSustain = 0.3;
constexpr double kFltRelease = 0.3;
constexpr double kFltEnvOctaves = 6.0;
constexpr double kFltVelOctaves = 6.0;

constexpr double kLfoRateModOctaves = 2.0;
constexpr double kLfoRateFloor = 0.01;
constexpr double kLfoRateCeil = 40.0;
constexpr double kLfoPitchSemitones = 2.0;
constexpr double kLfoFilterOctaves = 3.0;
constexpr double kLfoPwmRange = 0.25;
constexpr double kDefaultLfoRate = 5.0;

constexpr double kLadderKMax = 3.98;
constexpr double kLadderOscStart = 0.9;
constexpr double kLadderOscLevel = 0.35;

constexpr double kClipThreshold = 1.0;
constexpr double kLimiterCeiling = 0.98;
constexpr double kLimiterSilenceThreshold = 0.001;
constexpr double kLimiterSilenceS = 0.5;

constexpr double kDefaultMasterGain = 0.8;
constexpr double kFixedVelocity = 100.0 / 127.0;

constexpr double kTailSlotsMax = 12.0;
constexpr double kForcedReleaseS = 0.010;

}  // namespace snakeoil
