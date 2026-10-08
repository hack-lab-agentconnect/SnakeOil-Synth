#pragma once

#include <algorithm>
#include <cmath>
#include <vector>

#include "snakeoil/constants.hpp"

namespace snakeoil {

constexpr double kChorusMaxDepthMs = 8.0;
constexpr int kStereoSpread = 23;

inline int wrapIndex(long long value, int size) {
    const long long r = value % size;
    return static_cast<int>(r < 0 ? r + size : r);
}

inline double interpRead(const double* buf, int size, long long idx, int k, double delay) {
    double pos = static_cast<double>(idx + k) - delay;
    while (pos < 0.0) {
        pos += size;
    }
    const double whole = std::floor(pos);
    const double frac = pos - whole;
    const int i0 = wrapIndex(static_cast<long long>(whole), size);
    int i1 = i0 + 1;
    if (i1 >= size) {
        i1 = 0;
    }
    return buf[i0] * (1.0 - frac) + buf[i1] * frac;
}

// --- chorus -----------------------------------------------------------------

class Chorus {
public:
    explicit Chorus(double sr) : sr_(sr), inc_(2.0 * kPi * 0.5 / sr) {
        base_ = 14.0 * sr / 1000.0;
        setDepth(0.3);
        const int maxlen = static_cast<int>((14.0 + kChorusMaxDepthMs + 5.0) * sr / 1000.0) + 4;
        buf_[0].assign(static_cast<std::size_t>(maxlen), 0.0);
        buf_[1].assign(static_cast<std::size_t>(maxlen), 0.0);
    }

    void setEnabled(bool on) { enabled_ = on; }
    void setDepth(double amount) {
        amount = std::min(std::max(amount, 0.0), 1.0);
        depth_ = amount * kChorusMaxDepthMs * sr_ / 1000.0;
    }

    void process(double* left, double* right, int n) {
        if (!enabled_) {
            return;
        }
        const int limit = std::max(static_cast<int>(base_ - depth_) - 2, 1);
        for (int a = 0; a < n; a += limit) {
            const int b = std::min(a + limit, n);
            processChunk(left + a, right + a, b - a);
        }
    }

private:
    void processChunk(double* left, double* right, int n) {
        const int size = static_cast<int>(buf_[0].size());
        for (int k = 0; k < n; ++k) {
            mod_[k] = depth_ * std::sin(phase_ + inc_ * k);
        }
        double* in[2] = {left, right};
        for (int c = 0; c < 2; ++c) {
            const double sign = c == 0 ? 1.0 : -1.0;
            for (int k = 0; k < n; ++k) {
                wet_[k] = interpRead(buf_[c].data(), size, idx_, k, base_ + sign * mod_[k]);
            }
            for (int k = 0; k < n; ++k) {
                buf_[c][wrapIndex(idx_ + k, size)] = in[c][k] + wet_[k] * 0.15;
            }
            for (int k = 0; k < n; ++k) {
                in[c][k] += wet_[k] * 0.5;
            }
        }
        idx_ = wrapIndex(idx_ + n, size);
        phase_ = std::fmod(phase_ + inc_ * n, 2.0 * kPi);
    }

    double sr_;
    double inc_;
    double base_;
    double depth_ = 0.0;
    bool enabled_ = false;
    double phase_ = 0.0;
    long long idx_ = 0;
    std::vector<double> buf_[2];
    double mod_[kMaxBlock];
    double wet_[kMaxBlock];
};

// --- delay ------------------------------------------------------------------

class Delay {
public:
    explicit Delay(double sr) : sr_(sr) {
        buf_[0].assign(static_cast<std::size_t>(sr * 4.0) + 4, 0.0);
        buf_[1].assign(static_cast<std::size_t>(sr * 4.0) + 4, 0.0);
        setTimeMs(300.0);
    }

    void setEnabled(bool on) { enabled_ = on; }
    void setPingpong(bool on) { pingpong_ = on; }
    void setFeedback(double v) { feedback_ = std::min(std::max(v, 0.0), 0.95); }
    void setDamp(double v) { damp_ = std::min(std::max(v, 0.0), 0.9); }
    void setTimeMs(double ms) {
        timeMs_ = std::min(std::max(ms, 1.0), 4000.0);
        time_ = timeMs_ * sr_ / 1000.0;
    }

    void process(double* left, double* right, int n) {
        if (!enabled_) {
            return;
        }
        const int limit = std::max(static_cast<int>(time_), 1);
        for (int a = 0; a < n; a += limit) {
            const int b = std::min(a + limit, n);
            processChunk(left + a, right + a, b - a);
        }
    }

private:
    void processChunk(double* left, double* right, int n) {
        const int size = static_cast<int>(buf_[0].size());
        double* in[2] = {left, right};
        for (int c = 0; c < 2; ++c) {
            for (int k = 0; k < n; ++k) {
                wet_[c][k] = interpRead(buf_[c].data(), size, idx_, k, time_);
            }
            double state = filter_[c];
            for (int k = 0; k < n; ++k) {
                state = (1.0 - damp_) * wet_[c][k] + damp_ * state;
                filt_[c][k] = state;
            }
            filter_[c] = state;
        }
        if (pingpong_) {
            for (int k = 0; k < n; ++k) {
                buf_[0][wrapIndex(idx_ + k, size)] =
                    0.5 * (in[0][k] + in[1][k]) + filt_[1][k] * feedback_;
                buf_[1][wrapIndex(idx_ + k, size)] = filt_[0][k] * feedback_;
            }
        } else {
            for (int c = 0; c < 2; ++c) {
                for (int k = 0; k < n; ++k) {
                    buf_[c][wrapIndex(idx_ + k, size)] = in[c][k] + filt_[c][k] * feedback_;
                }
            }
        }
        idx_ = wrapIndex(idx_ + n, size);
        for (int c = 0; c < 2; ++c) {
            for (int k = 0; k < n; ++k) {
                in[c][k] += wet_[c][k] * 0.35;
            }
        }
    }

    double sr_;
    double timeMs_ = 300.0;
    double time_ = 0.0;
    double feedback_ = 0.35;
    double damp_ = 0.25;
    bool enabled_ = false;
    bool pingpong_ = false;
    long long idx_ = 0;
    double filter_[2] = {0.0, 0.0};
    std::vector<double> buf_[2];
    double wet_[2][kMaxBlock];
    double filt_[2][kMaxBlock];
};

// --- reverb -----------------------------------------------------------------

class Reverb {
public:
    explicit Reverb(double sr) : sr_(sr) {
        const double k = sr / 44100.0;
        const int combDelays[6] = {1116, 1188, 1277, 1356, 1422, 1491};
        const int apDelays[3] = {556, 441, 341};
        for (int i = 0; i < 6; ++i) {
            combsL_.emplace_back(static_cast<int>(combDelays[i] * k), room_, damp_);
            combsR_.emplace_back(static_cast<int>((combDelays[i] + kStereoSpread) * k), room_, damp_);
        }
        for (int i = 0; i < 3; ++i) {
            apL_.emplace_back(static_cast<int>(apDelays[i] * k));
            apR_.emplace_back(static_cast<int>((apDelays[i] + kStereoSpread) * k));
        }
    }

    void setEnabled(bool on) { enabled_ = on; }
    void setAmount(double v) { mix_ = std::min(std::max(v, 0.0), 1.0); }
    void setRoom(double v) {
        room_ = std::min(std::max(v, 0.5), 0.98);
        for (auto* c : allCombs()) {
            c->fb = room_;
        }
    }
    void setDamp(double v) {
        damp_ = std::min(std::max(v, 0.0), 0.9);
        for (auto* c : allCombs()) {
            c->damp = damp_;
        }
    }

    void process(double* left, double* right, int n) {
        if (!enabled_) {
            return;
        }
        int limit = n;
        for (auto* c : allCombs()) {
            limit = std::min(limit, c->size());
        }
        for (auto* a : allAllpasses()) {
            limit = std::min(limit, a->size());
        }
        for (int a = 0; a < n; a += limit) {
            const int b = std::min(a + limit, n);
            bank(left + a, left + a, combsL_, apL_, b - a);
            bank(right + a, right + a, combsR_, apR_, b - a);
        }
    }

private:
    struct Comb {
        std::vector<double> buf;
        long long idx = 0;
        double fb;
        double damp;
        double filter = 0.0;
        Comb(int delay, double feedback, double damping)
            : buf(static_cast<std::size_t>(delay), 0.0), fb(feedback), damp(damping) {}
        int size() const { return static_cast<int>(buf.size()); }
    };
    struct Allpass {
        std::vector<double> buf;
        long long idx = 0;
        double fb = 0.5;
        explicit Allpass(int delay) : buf(static_cast<std::size_t>(delay), 0.0) {}
        int size() const { return static_cast<int>(buf.size()); }
    };

    std::vector<Comb*> allCombs() {
        std::vector<Comb*> out;
        for (auto& c : combsL_) out.push_back(&c);
        for (auto& c : combsR_) out.push_back(&c);
        return out;
    }
    std::vector<Allpass*> allAllpasses() {
        std::vector<Allpass*> out;
        for (auto& a : apL_) out.push_back(&a);
        for (auto& a : apR_) out.push_back(&a);
        return out;
    }

    void bank(const double* x, double* out, std::vector<Comb>& combs,
              std::vector<Allpass>& aps, int n) {
        for (int k = 0; k < n; ++k) {
            sum_[k] = 0.0;
        }
        for (auto& c : combs) {
            const int size = c.size();
            for (int k = 0; k < n; ++k) {
                y_[k] = c.buf[wrapIndex(c.idx + k, size)];
            }
            double state = c.filter;
            for (int k = 0; k < n; ++k) {
                state = (1.0 - c.damp) * y_[k] + c.damp * state;
                filt_[k] = state;
            }
            c.filter = state;
            for (int k = 0; k < n; ++k) {
                c.buf[wrapIndex(c.idx + k, size)] = x[k] + filt_[k] * c.fb;
            }
            c.idx = wrapIndex(c.idx + n, size);
            for (int k = 0; k < n; ++k) {
                sum_[k] += y_[k];
            }
        }
        const double inv = 1.0 / static_cast<double>(combs.size());
        for (int k = 0; k < n; ++k) {
            sum_[k] *= inv;
        }
        for (auto& a : aps) {
            const int size = a.size();
            for (int k = 0; k < n; ++k) {
                y_[k] = a.buf[wrapIndex(a.idx + k, size)];
            }
            for (int k = 0; k < n; ++k) {
                a.buf[wrapIndex(a.idx + k, size)] = sum_[k] + y_[k] * a.fb;
            }
            a.idx = wrapIndex(a.idx + n, size);
            for (int k = 0; k < n; ++k) {
                sum_[k] = y_[k] - sum_[k];
            }
        }
        for (int k = 0; k < n; ++k) {
            out[k] = x[k] + sum_[k] * mix_;
        }
    }

    double sr_;
    double mix_ = 0.3;
    double room_ = 0.84;
    double damp_ = 0.25;
    bool enabled_ = false;
    std::vector<Comb> combsL_, combsR_;
    std::vector<Allpass> apL_, apR_;
    double y_[kMaxBlock];
    double filt_[kMaxBlock];
    double sum_[kMaxBlock];
};

// --- bitcrusher -------------------------------------------------------------

class Bitcrusher {
public:
    void setEnabled(bool on) { enabled_ = on; }
    void setAmount(double a) {
        a = std::min(std::max(a, 0.0), 1.0);
        bits_ = std::max(2, static_cast<int>(std::lround(16.0 - 16.0 * a)));
        downsample_ = std::max(1, static_cast<int>(std::lround(1.0 + 6.0 * a)));
    }

    void process(double* left, double* right, int n) {
        if (!enabled_ || n == 0) {
            return;
        }
        const double levels = static_cast<double>(1 << std::max(bits_, 1));
        int counter = counter_;
        double hold0 = hold_[0];
        double hold1 = hold_[1];
        for (int k = 0; k < n; ++k) {
            if (counter <= 0) {
                hold0 = left[k];
                hold1 = right[k];
                counter = downsample_;
            }
            --counter;
            left[k] = std::round(hold0 * levels) / levels;
            right[k] = std::round(hold1 * levels) / levels;
        }
        counter_ = counter;
        hold_[0] = hold0;
        hold_[1] = hold1;
    }

private:
    bool enabled_ = false;
    int bits_ = 8;
    int downsample_ = 4;
    int counter_ = 0;
    double hold_[2] = {0.0, 0.0};
};

class EffectChain {
public:
    explicit EffectChain(double sr) : chorus_(sr), delay_(sr), reverb_(sr) {
        bitcrush_.setAmount(0.5);
    }

    Chorus& chorus() { return chorus_; }
    Delay& delay() { return delay_; }
    Reverb& reverb() { return reverb_; }
    Bitcrusher& bitcrush() { return bitcrush_; }

    void process(double* left, double* right, int n) {
        chorus_.process(left, right, n);
        delay_.process(left, right, n);
        reverb_.process(left, right, n);
        bitcrush_.process(left, right, n);
    }

private:
    Chorus chorus_;
    Delay delay_;
    Reverb reverb_;
    Bitcrusher bitcrush_;
};

}  // namespace snakeoil
