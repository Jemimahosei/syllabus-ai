// SyllabusAI parser — C++ parser module.
//
// Reads a syllabus as plain text on stdin, extracts structured information
// (course info, AI policy, grading breakdown, slip days / late policy,
// key deadlines, required materials) and prints a single JSON object.
//
// Design mirror: this is the "C++ parser" half of the SyllabusAI
// architecture. The Python service (app/) calls this binary and hands its
// JSON to the rules engine (app/rules.py), which mirrors the OCaml
// rules-engine half: named rules (AI_POLICY, GRADING, SLIP_DAYS,
// LATE_POLICY, DEADLINES, MATERIALS) turn parsed facts into takeaways.
//
// Build:  g++ -std=c++17 -O2 -o syllabus_parser syllabus_parser.cpp
// Usage:  ./syllabus_parser < syllabus.txt
#include <algorithm>
#include <cctype>
#include <iostream>
#include <map>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

static std::string toLower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return s;
}

static std::string trim(const std::string& s) {
    size_t a = 0;
    while (a < s.size() && std::isspace((unsigned char)s[a])) a++;
    size_t b = s.size();
    while (b > a && std::isspace((unsigned char)s[b - 1])) b--;
    return s.substr(a, b - a);
}

// Normalize UTF-8 punctuation to ASCII so regexes stay simple.
static std::string normalize(const std::string& in) {
    std::string out;
    for (size_t i = 0; i < in.size();) {
        unsigned char c = (unsigned char)in[i];
        if (c == 0xE2 && i + 2 < in.size()) {
            unsigned char c2 = (unsigned char)in[i + 1];
            unsigned char c3 = (unsigned char)in[i + 2];
            if (c2 == 0x80 && (c3 == 0x93 || c3 == 0x94)) { out += '-'; i += 3; continue; } // en/em dash
            if (c2 == 0x80 && (c3 == 0x98 || c3 == 0x99)) { out += '\''; i += 3; continue; } // single quotes
            if (c2 == 0x80 && (c3 == 0x9C || c3 == 0x9D)) { out += '"'; i += 3; continue; } // double quotes
            if (c2 == 0x80 && c3 == 0xA2) { out += '-'; i += 3; continue; } // bullet
            if (c2 == 0x80 && c3 == 0xA6) { out += "..."; i += 3; continue; } // ellipsis
        }
        if (c == 0xC2 && i + 1 < in.size() && (unsigned char)in[i + 1] == 0xA0) {
            out += ' '; i += 2; continue; // nbsp
        }
        out += in[i];
        i++;
    }
    return out;
}

static std::string jsonEscape(const std::string& s) {
    std::string out;
    for (unsigned char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else out += (char)c;
        }
    }
    return out;
}

static std::vector<std::string> splitLines(const std::string& s) {
    std::vector<std::string> lines;
    std::stringstream ss(s);
    std::string line;
    while (std::getline(ss, line)) lines.push_back(line);
    return lines;
}

static std::vector<std::string> splitSentences(const std::string& s) {
    std::vector<std::string> out;
    std::string cur;
    for (size_t i = 0; i < s.size(); i++) {
        cur += s[i];
        if ((s[i] == '.' || s[i] == '!' || s[i] == '?') &&
            (i + 1 >= s.size() || s[i + 1] == ' ' || s[i + 1] == '\n')) {
            std::string t = trim(cur);
            if (!t.empty()) out.push_back(t);
            cur.clear();
        }
    }
    std::string t = trim(cur);
    if (!t.empty()) out.push_back(t);
    return out;
}

static bool containsWord(const std::string& low, const std::string& w) {
    return low.find(w) != std::string::npos;
}

// ---------- section segmentation ----------
struct Section {
    std::string heading;
    std::string text; // joined lines
};

static const std::vector<std::string> kHeadingKeywords = {
    "course description", "course overview", "about this course",
    "learning objectives", "course objectives", "what you will learn",
    "required materials", "materials", "textbook", "required texts",
    "readings", "grading", "grade breakdown", "how you will be graded",
    "assessment", "artificial intelligence", "ai policy", "generative ai",
    "use of ai", "late work", "late policy", "slip days", "extensions",
    "schedule", "key dates", "important dates", "course schedule",
    "calendar", "academic integrity", "honesty", "attendance",
    "participation", "exams", "assignments", "course policies", "policies",
    "prerequisites", "instructor", "office hours", "communication",
};

static bool isHeading(const std::string& raw, std::string& headingOut) {
    std::string line = trim(raw);
    if (line.empty()) return false;
    // Bulleted / list lines are content, never headings.
    if (line[0] == '-' || line[0] == '*' || line.rfind("•", 0) == 0) return false;
    // Markdown heading
    if (line[0] == '#') {
        std::string h = trim(line.substr(line.find_first_not_of('#')));
        if (!h.empty()) { headingOut = h; return true; }
        return false;
    }
    if (line.size() > 70) return false;
    std::string low = toLower(line);
    // Numbered heading: "1. Course Policies"
    {
        static const std::regex numRe(R"(^\d+[.)]\s+[A-Z].{2,60}$)");
        if (std::regex_match(line, numRe)) {
            headingOut = std::regex_replace(line, std::regex(R"(^\d+[.)]\s+)"), "");
            return true;
        }
    }
    // Trailing colon heading ("Grading:"), but not "as follows:" lines
    // or sentence lead-ins like "By the end of the course, ...:".
    if (line.back() == ':' && line.find('.') == std::string::npos &&
        line.size() <= 45 &&
        low.find("as follows") == std::string::npos &&
        low.find("following") == std::string::npos &&
        low.find("will be able") == std::string::npos &&
        low.rfind("by ", 0) != 0) {
        headingOut = trim(line.substr(0, line.size() - 1));
        return true;
    }
    // ALL-CAPS heading
    {
        bool hasAlpha = false, allUpper = true;
        for (char ch : line) {
            if (std::isalpha((unsigned char)ch)) {
                hasAlpha = true;
                if (std::islower((unsigned char)ch)) allUpper = false;
            }
        }
        if (hasAlpha && allUpper && line.size() >= 4) { headingOut = line; return true; }
    }
    // Known heading phrase (title case / any case, short line).
    // A line carrying a percentage ("Assignments: 50%") is data, not a heading.
    if (line.find('%') != std::string::npos) return false;
    for (const auto& kw : kHeadingKeywords) {
        if (low == kw || low.find(kw) != std::string::npos) {
            // Avoid treating long content lines as headings: require the
            // keyword to cover most of the line.
            if (line.size() <= (kw.size() + 25)) { headingOut = line; return true; }
        }
    }
    return false;
}

static std::vector<Section> segment(const std::vector<std::string>& lines) {
    std::vector<Section> sections;
    Section cur;
    cur.heading = "";
    for (const auto& raw : lines) {
        std::string h;
        if (isHeading(raw, h)) {
            if (!trim(cur.text).empty() || !cur.heading.empty()) sections.push_back(cur);
            cur.heading = h;
            cur.text = "";
        } else {
            if (!cur.text.empty()) cur.text += "\n";
            cur.text += raw;
        }
    }
    if (!trim(cur.text).empty() || !cur.heading.empty()) sections.push_back(cur);
    return sections;
}

static std::string joinSectionsText(const std::vector<Section>& sections) {
    std::string out;
    for (const auto& s : sections) {
        if (!s.heading.empty()) { if (!out.empty()) out += "\n"; out += s.heading + "\n"; }
        if (!out.empty() && !s.text.empty()) out += "\n";
        out += s.text;
    }
    return out;
}

static const Section* findSection(const std::vector<Section>& sections,
                                  const std::vector<std::string>& keywords) {
    for (const auto& s : sections) {
        std::string low = toLower(s.heading);
        for (const auto& kw : keywords)
            if (low.find(kw) != std::string::npos) return &s;
    }
    return nullptr;
}

// ---------- extraction helpers ----------
static int wordToNum(const std::string& w) {
    static const std::map<std::string, int> m = {
        {"one", 1}, {"two", 2}, {"three", 3}, {"four", 4}, {"five", 5},
        {"six", 6}, {"seven", 7}, {"eight", 8}, {"nine", 9}, {"ten", 10},
    };
    auto it = m.find(toLower(w));
    if (it != m.end()) return it->second;
    try { return std::stoi(w); } catch (...) { return -1; }
}

static int monthNum(const std::string& m) {
    std::string l = toLower(m);
    if (l.rfind("jan", 0) == 0) return 1;
    if (l.rfind("feb", 0) == 0) return 2;
    if (l.rfind("mar", 0) == 0) return 3;
    if (l.rfind("apr", 0) == 0) return 4;
    if (l == "may") return 5;
    if (l.rfind("jun", 0) == 0) return 6;
    if (l.rfind("jul", 0) == 0) return 7;
    if (l.rfind("aug", 0) == 0) return 8;
    if (l.rfind("sep", 0) == 0) return 9;
    if (l.rfind("oct", 0) == 0) return 10;
    if (l.rfind("nov", 0) == 0) return 11;
    if (l.rfind("dec", 0) == 0) return 12;
    return 0;
}

static std::string twoDigit(int n) {
    return (n < 10 ? "0" : "") + std::to_string(n);
}

struct GradingItem { std::string label; int percent; };
struct Deadline { std::string label; std::string dateRaw; std::string dateNorm; std::string kind; std::string context; };

int main() {
    std::ostringstream ss;
    ss << std::cin.rdbuf();
    std::string raw = normalize(ss.str());
    std::vector<std::string> lines = splitLines(raw);
    std::vector<Section> sections = segment(lines);
    std::string allText = joinSectionsText(sections);
    std::string allLow = toLower(allText);

    // ----- course info -----
    std::string code, title, instructor, term;
    {
        static const std::regex codeRe(R"(\b([A-Z]{2,4}\s*\d{3,4}[A-Z]?)\s*[:\-–—]\s*(.+))");
        std::smatch m;
        for (const auto& ln : lines) {
            if (std::regex_search(ln, m, codeRe)) {
                code = trim(m[1].str());
                code = std::regex_replace(code, std::regex(R"(\s+)"), " ");
                title = trim(m[2].str());
                if (title.size() > 80) title = title.substr(0, 80);
                break;
            }
        }
        static const std::regex instrRe(R"(Instructor\s*:\s*(.+))", std::regex::icase);
        if (std::regex_search(allText, m, instrRe)) instructor = trim(m[1].str());
        static const std::regex termRe(R"((Fall|Spring|Summer|Winter)\s+(20\d{2}))", std::regex::icase);
        if (std::regex_search(allText, m, termRe)) term = m[1].str() + " " + m[2].str();
    }

    // ----- AI policy -----
    std::string aiText, aiStance = "not_stated";
    bool aiFound = false;
    {
        const Section* s = findSection(sections, {"artificial intelligence", "ai policy", "generative ai", "use of ai"});
        if (s) { aiText = trim(s->text); aiFound = !aiText.empty(); }
        if (!aiFound) {
            // Fallback: paragraph mentioning AI tools + policy-ish words.
            static const std::regex aiRe(R"(([^.\n]*(artificial intelligence|generative ai|ChatGPT|AI tool)[^.\n]*\.)[^.\n]*)", std::regex::icase);
            std::smatch m;
            if (std::regex_search(allText, m, aiRe)) { aiText = trim(m[0].str()); aiFound = true; }
        }
        if (aiFound) {
            std::string l = toLower(aiText);
            bool allows = containsWord(l, "may be used") || containsWord(l, "may use") ||
                          containsWord(l, "allowed") || containsWord(l, "permitted") ||
                          containsWord(l, "you may") || containsWord(l, "encouraged");
            bool restricts = containsWord(l, "may not") || containsWord(l, "not permitted") ||
                             containsWord(l, "prohibited") || containsWord(l, "not allowed") ||
                             containsWord(l, "must not") || containsWord(l, "do not use");
            if (allows && restricts) aiStance = "allowed_with_rules";
            else if (restricts) aiStance = "prohibited";
            else if (allows) aiStance = "allowed";
            else aiStance = "unclear";
        }
    }
    std::vector<std::string> aiQuotes;
    if (aiFound) {
        for (const auto& sent : splitSentences(aiText)) {
            std::string l = toLower(sent);
            if (containsWord(l, "must") || containsWord(l, "may not") ||
                containsWord(l, "disclosure") || containsWord(l, "not submit")) {
                aiQuotes.push_back(sent);
                if (aiQuotes.size() >= 2) break;
            }
        }
        if (aiQuotes.empty() && !splitSentences(aiText).empty())
            aiQuotes.push_back(splitSentences(aiText)[0]);
    }

    // ----- grading -----
    std::vector<GradingItem> grading;
    int gradingTotal = 0;
    {
        std::string scope;
        const Section* s = findSection(sections, {"grading", "grade breakdown", "how you will be graded", "assessment"});
        if (s) scope = s->text;
        else scope = allText;
        static const std::regex itemRe(R"(^\s*[-•*]?\s*([A-Za-z][A-Za-z0-9 &/'\-()]{2,70}?)\s*[:\-–—]\s*(\d{1,3})\s*%)");
        static const std::regex itemRe2(R"(^\s*[-•*]?\s*([A-Za-z][A-Za-z0-9 &/'\-()]{2,70}?)\s+(\d{1,3})\s*%)");
        for (const auto& ln : splitLines(scope)) {
            std::string low = toLower(ln);
            if (low.find("per day") != std::string::npos ||
                low.find("late") != std::string::npos ||
                low.find("lose") != std::string::npos ||
                low.find("loses") != std::string::npos) continue;
            std::smatch m;
            if (std::regex_search(ln, m, itemRe) || std::regex_search(ln, m, itemRe2)) {
                std::string label = trim(m[1].str());
                label = std::regex_replace(label, std::regex(R"(\s*\(\d+\s+total\)\s*$)"), "");
                label = std::regex_replace(label, std::regex(R"(\s+)"), " ");
                int pct = std::stoi(m[2].str());
                if (pct < 0 || pct > 100) continue;
                bool dup = false;
                for (const auto& g : grading)
                    if (toLower(g.label) == toLower(label)) { dup = true; break; }
                if (!dup && label.size() >= 3) {
                    grading.push_back({label, pct});
                    gradingTotal += pct;
                }
            }
        }
    }

    // ----- slip days + late policy -----
    int slipCount = -1;
    std::string slipText, lateText;
    bool slipFound = false, lateFound = false;
    {
        const Section* s = findSection(sections, {"late work", "late policy", "slip days", "extensions"});
        if (s) { lateText = trim(s->text); lateFound = !lateText.empty(); }
        static const std::regex slipRe(R"((\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+slip\s+days?)", std::regex::icase);
        std::smatch m;
        std::string scope = lateFound ? lateText : allText;
        if (std::regex_search(scope, m, slipRe)) {
            slipCount = wordToNum(m[1].str());
            slipFound = slipCount >= 0;
        }
        if (slipFound) {
            // sentences mentioning slip days, from the late section or whole text
            std::vector<std::string> sents = splitSentences(lateFound ? lateText : allText);
            std::string acc;
            for (const auto& sent : sents) {
                if (toLower(sent).find("slip") != std::string::npos) {
                    if (!acc.empty()) acc += " ";
                    acc += sent;
                    if (acc.size() > 700) break;
                }
            }
            slipText = acc;
        }
        if (!lateFound) {
            std::vector<std::string> sents = splitSentences(allText);
            std::string acc;
            for (const auto& sent : sents) {
                std::string l = toLower(sent);
                if (l.find("late") != std::string::npos &&
                    (l.find("lose") != std::string::npos || l.find("penalt") != std::string::npos ||
                     l.find("not accepted") != std::string::npos || l.find("per day") != std::string::npos)) {
                    if (!acc.empty()) acc += " ";
                    acc += sent;
                }
            }
            if (!acc.empty()) { lateText = acc; lateFound = true; }
        }
        if ((int)lateText.size() > 1200) lateText = lateText.substr(0, 1200);
        if ((int)slipText.size() > 900) slipText = slipText.substr(0, 900);
    }

    // ----- deadlines -----
    std::vector<Deadline> deadlines;
    {
        static const std::regex dateRe(
            R"((January|February|March|April|May|June|July|August|September|Sept\.?|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Oct\.?|Nov\.?|Dec\.?)\s+(\d{1,2})(?:\s*[–—\-]\s*(\d{1,2}))?(?:,\s*(\d{4}))?)",
            std::regex::icase);
        static const std::regex numDateRe(R"(\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b)");
        const Section* sched = findSection(sections, {"schedule", "key dates", "important dates", "course schedule", "calendar"});
        std::vector<std::string> candLines;
        if (sched) {
            for (const auto& ln : splitLines(sched->text)) candLines.push_back(ln);
        }
        // Also accept due/exam lines from anywhere in the text.
        for (const auto& ln : lines) {
            std::string l = toLower(ln);
            if ((l.find("due") != std::string::npos || l.find("exam") != std::string::npos ||
                 l.find("midterm") != std::string::npos || l.find("final") != std::string::npos) &&
                (std::regex_search(ln, dateRe) || std::regex_search(ln, numDateRe))) {
                bool dup = false;
                for (const auto& c : candLines) if (c == ln) { dup = true; break; }
                if (!dup) candLines.push_back(ln);
            }
        }
        for (const auto& ln : candLines) {
            std::string l = toLower(ln);
            if (l.find("no assignment due") != std::string::npos) continue;
            if (l.find("no class") != std::string::npos) continue;
            std::smatch m;
            std::string dateRaw, dateNorm;
            if (std::regex_search(ln, m, dateRe)) {
                dateRaw = m[0].str();
                int mo = monthNum(m[1].str());
                int day = std::stoi(m[2].str());
                std::string year = m[4].matched ? m[4].str() : "";
                if (mo && !year.empty()) dateNorm = year + "-" + twoDigit(mo) + "-" + twoDigit(day);
            } else if (std::regex_search(ln, m, numDateRe)) {
                dateRaw = m[0].str();
                int mo = std::stoi(m[1].str());
                int day = std::stoi(m[2].str());
                if (m[3].matched) {
                    std::string y = m[3].str();
                    if (y.size() == 2) y = "20" + y;
                    dateNorm = y + "-" + twoDigit(mo) + "-" + twoDigit(day);
                }
            } else continue;
            // Label: line minus the date, cleaned of weekday/time/bullets.
            std::string label = ln;
            size_t pos = label.find(dateRaw);
            if (pos != std::string::npos) label.erase(pos, dateRaw.size());
            label = std::regex_replace(label, std::regex(R"(^\s*[-•*]\s*)"), "");
            label = std::regex_replace(label, std::regex(R"(\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*)", std::regex::icase), "");
            label = std::regex_replace(label, std::regex(R"((,?\s*\d{1,2}:\d{2}\s*(AM|PM|am|pm)?\.?)\s*$)"), "");
            label = std::regex_replace(label, std::regex(R"(,\s*,)"), ",");
            label = std::regex_replace(label, std::regex(R"(:\s*,)"), ":");
            label = std::regex_replace(label, std::regex(R"(\s+)"), " ");
            label = trim(label);
            // Iteratively strip trailing punctuation left behind.
            while (!label.empty() && std::string(",.:;-").find(label.back()) != std::string::npos) {
                label = trim(label.substr(0, label.size() - 1));
            }
            // Deadline lines are usually "Thing due: <date>"; the label is
            // the part before the first colon.
            size_t colon = label.find(':');
            if (colon != std::string::npos) label = trim(label.substr(0, colon));
            // Drop parenthetical week markers at the start: "Week 1 (Aug 27): ..." handled above; keep if label empty
            if (label.empty()) {
                label = trim(std::regex_replace(ln, std::regex(R"(\s+)"), " "));
            }
            std::string kind = "other";
            std::string kl = toLower(label + " " + ln);
            if (kl.find("midterm") != std::string::npos) kind = "midterm";
            else if (kl.find("final project") != std::string::npos) kind = "final_project";
            else if (kl.find("final exam") != std::string::npos) kind = "final_exam";
            else if (kl.find("final") != std::string::npos) kind = "final";
            else if (kl.find("quiz") != std::string::npos) kind = "quiz";
            else if (kl.find("proposal") != std::string::npos) kind = "proposal";
            else if (kl.find("presentation") != std::string::npos) kind = "presentation";
            else if (kl.find("homework") != std::string::npos || kl.find("assignment") != std::string::npos) kind = "homework";
            else if (kl.find("project") != std::string::npos) kind = "project";
            else if (kl.find("exam") != std::string::npos) kind = "exam";
            bool dup = false;
            for (const auto& d : deadlines)
                if (d.label == label && d.dateRaw == dateRaw) { dup = true; break; }
            if (!dup) deadlines.push_back({label, dateRaw, dateNorm, kind, trim(ln)});
        }
    }

    // ----- materials -----
    std::vector<std::string> materials;
    {
        const Section* s = findSection(sections, {"required materials", "materials", "textbook", "required texts", "readings"});
        if (s) {
            for (const auto& ln : splitLines(s->text)) {
                std::string t = trim(ln);
                if (t.empty()) continue;
                t = std::regex_replace(t, std::regex(R"(^\s*[-•*]\s*)"), "");
                t = trim(t);
                if (t.size() < 3) continue;
                // Join wrapped continuation lines (lowercase start, previous exists)
                if (!materials.empty() && !t.empty() && std::islower((unsigned char)t[0]) &&
                    t.find("ISBN") == std::string::npos) {
                    materials.back() += " " + t;
                } else {
                    materials.push_back(t);
                }
            }
        }
    }

    // ----- emit JSON -----
    std::ostringstream out;
    out << "{";
    out << "\"course\":{";
    out << "\"code\":\"" << jsonEscape(code) << "\",";
    out << "\"title\":\"" << jsonEscape(title) << "\",";
    out << "\"instructor\":\"" << jsonEscape(instructor) << "\",";
    out << "\"term\":\"" << jsonEscape(term) << "\"},";
    out << "\"ai_policy\":{";
    out << "\"found\":" << (aiFound ? "true" : "false") << ",";
    out << "\"stance\":\"" << aiStance << "\",";
    out << "\"text\":\"" << jsonEscape(aiText.size() > 2000 ? aiText.substr(0, 2000) : aiText) << "\",";
    out << "\"quotes\":[";
    for (size_t i = 0; i < aiQuotes.size(); i++) {
        if (i) out << ",";
        out << "\"" << jsonEscape(aiQuotes[i]) << "\"";
    }
    out << "]},";
    out << "\"grading\":{\"items\":[";
    for (size_t i = 0; i < grading.size(); i++) {
        if (i) out << ",";
        out << "{\"label\":\"" << jsonEscape(grading[i].label) << "\",\"percent\":" << grading[i].percent << "}";
    }
    out << "],\"total\":" << gradingTotal << "},";
    out << "\"slip_days\":{\"found\":" << (slipFound ? "true" : "false") << ",";
    out << "\"count\":" << slipCount << ",";
    out << "\"text\":\"" << jsonEscape(slipText) << "\"},";
    out << "\"late_policy\":{\"found\":" << (lateFound ? "true" : "false") << ",";
    out << "\"text\":\"" << jsonEscape(lateText) << "\"},";
    out << "\"deadlines\":[";
    for (size_t i = 0; i < deadlines.size(); i++) {
        if (i) out << ",";
        out << "{\"label\":\"" << jsonEscape(deadlines[i].label) << "\",";
        out << "\"date_raw\":\"" << jsonEscape(deadlines[i].dateRaw) << "\",";
        out << "\"date\":\"" << jsonEscape(deadlines[i].dateNorm) << "\",";
        out << "\"kind\":\"" << deadlines[i].kind << "\",";
        out << "\"context\":\"" << jsonEscape(deadlines[i].context) << "\"}";
    }
    out << "],";
    out << "\"materials\":[";
    for (size_t i = 0; i < materials.size(); i++) {
        if (i) out << ",";
        out << "\"" << jsonEscape(materials[i]) << "\"";
    }
    out << "],";
    out << "\"sections\":[";
    bool first = true;
    for (const auto& s : sections) {
        if (s.heading.empty()) continue;
        if (!first) out << ",";
        first = false;
        out << "{\"heading\":\"" << jsonEscape(s.heading) << "\",";
        std::string t = s.text.size() > 1500 ? s.text.substr(0, 1500) : s.text;
        out << "\"text\":\"" << jsonEscape(t) << "\"}";
    }
    out << "]";
    out << "}";
    std::cout << out.str() << "\n";
    return 0;
}
