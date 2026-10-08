#pragma once

// A tiny JSON reader for the golden scenario files only. It supports the subset
// used by tools/export_cpp_golden.py: objects, arrays, numbers, strings,
// booleans and null. It is deliberately dependency-free (no third-party JSON).

#include <cctype>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace jsonmini {

struct Value {
    enum Type { kNull, kBool, kNumber, kString, kArray, kObject };
    Type type = kNull;
    bool boolean = false;
    double number = 0.0;
    std::string str;
    std::vector<Value> array;
    std::vector<std::pair<std::string, Value>> object;

    const Value* find(const std::string& key) const {
        for (const auto& entry : object) {
            if (entry.first == key) {
                return &entry.second;
            }
        }
        return nullptr;
    }

    bool isNumber() const { return type == kNumber; }
    bool isString() const { return type == kString; }
    bool isArray() const { return type == kArray; }
    bool isObject() const { return type == kObject; }
};

class Parser {
public:
    explicit Parser(const std::string& text) : s_(text) {}

    Value parse() {
        skipSpace();
        Value value = parseValue();
        skipSpace();
        if (pos_ != s_.size()) {
            fail("trailing characters");
        }
        return value;
    }

private:
    [[noreturn]] void fail(const std::string& message) const {
        throw std::runtime_error("json: " + message + " at offset " + std::to_string(pos_));
    }

    void skipSpace() {
        while (pos_ < s_.size() &&
               (s_[pos_] == ' ' || s_[pos_] == '\t' || s_[pos_] == '\n' ||
                s_[pos_] == '\r')) {
            ++pos_;
        }
    }

    char peek() {
        if (pos_ >= s_.size()) {
            fail("unexpected end of input");
        }
        return s_[pos_];
    }

    void expect(char c) {
        if (peek() != c) {
            fail(std::string("expected '") + c + "'");
        }
        ++pos_;
    }

    Value parseValue() {
        switch (peek()) {
            case '{':
                return parseObject();
            case '[':
                return parseArray();
            case '"': {
                Value value;
                value.type = Value::kString;
                value.str = parseString();
                return value;
            }
            case 't': {
                expectWord("true");
                Value value;
                value.type = Value::kBool;
                value.boolean = true;
                return value;
            }
            case 'f': {
                expectWord("false");
                Value value;
                value.type = Value::kBool;
                value.boolean = false;
                return value;
            }
            case 'n': {
                expectWord("null");
                return Value{};
            }
            default:
                return parseNumber();
        }
    }

    void expectWord(const char* word) {
        const std::string w(word);
        if (s_.compare(pos_, w.size(), w) != 0) {
            fail("invalid literal");
        }
        pos_ += w.size();
    }

    Value parseObject() {
        Value value;
        value.type = Value::kObject;
        expect('{');
        skipSpace();
        if (peek() == '}') {
            ++pos_;
            return value;
        }
        while (true) {
            skipSpace();
            std::string key = parseString();
            skipSpace();
            expect(':');
            skipSpace();
            value.object.emplace_back(std::move(key), parseValue());
            skipSpace();
            const char c = peek();
            if (c == ',') {
                ++pos_;
            } else if (c == '}') {
                ++pos_;
                break;
            } else {
                fail("expected ',' or '}'");
            }
        }
        return value;
    }

    Value parseArray() {
        Value value;
        value.type = Value::kArray;
        expect('[');
        skipSpace();
        if (peek() == ']') {
            ++pos_;
            return value;
        }
        while (true) {
            skipSpace();
            value.array.push_back(parseValue());
            skipSpace();
            const char c = peek();
            if (c == ',') {
                ++pos_;
            } else if (c == ']') {
                ++pos_;
                break;
            } else {
                fail("expected ',' or ']'");
            }
        }
        return value;
    }

    std::string parseString() {
        expect('"');
        std::string out;
        while (true) {
            if (pos_ >= s_.size()) {
                fail("unterminated string");
            }
            const char c = s_[pos_++];
            if (c == '"') {
                break;
            }
            if (c == '\\') {
                if (pos_ >= s_.size()) {
                    fail("bad escape");
                }
                const char e = s_[pos_++];
                switch (e) {
                    case '"': out.push_back('"'); break;
                    case '\\': out.push_back('\\'); break;
                    case '/': out.push_back('/'); break;
                    case 'n': out.push_back('\n'); break;
                    case 't': out.push_back('\t'); break;
                    case 'r': out.push_back('\r'); break;
                    case 'b': out.push_back('\b'); break;
                    case 'f': out.push_back('\f'); break;
                    default: fail("unsupported escape");
                }
            } else {
                out.push_back(c);
            }
        }
        return out;
    }

    Value parseNumber() {
        const std::size_t start = pos_;
        if (peek() == '-' || peek() == '+') {
            ++pos_;
        }
        while (pos_ < s_.size() &&
               (std::isdigit(static_cast<unsigned char>(s_[pos_])) ||
                s_[pos_] == '.' || s_[pos_] == 'e' || s_[pos_] == 'E' ||
                s_[pos_] == '+' || s_[pos_] == '-')) {
            ++pos_;
        }
        if (pos_ == start) {
            fail("invalid number");
        }
        Value value;
        value.type = Value::kNumber;
        value.number = std::strtod(s_.substr(start, pos_ - start).c_str(), nullptr);
        return value;
    }

    const std::string& s_;
    std::size_t pos_ = 0;
};

inline Value parse(const std::string& text) {
    return Parser(text).parse();
}

}  // namespace jsonmini
