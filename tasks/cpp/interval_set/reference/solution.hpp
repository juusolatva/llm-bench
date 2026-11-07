#pragma once
#include <iterator>
#include <map>
#include <utility>
#include <vector>

// A set of integers stored as disjoint, non-touching half-open intervals in a map from start to end.
class IntervalSet {
public:
    // Add [lo, hi), merging every stored interval it overlaps or touches.
    void add(long lo, long hi) {
        if (lo >= hi) return;
        auto it = map_.upper_bound(lo);
        if (it != map_.begin() && std::prev(it)->second >= lo) {
            --it;
            lo = it->first;
        }
        while (it != map_.end() && it->first <= hi) {
            if (it->second > hi) hi = it->second;
            it = map_.erase(it);
        }
        map_.emplace(lo, hi);
    }

    // Remove [lo, hi), trimming or splitting the stored intervals it overlaps.
    void remove(long lo, long hi) {
        if (lo >= hi) return;
        auto it = map_.upper_bound(lo);
        if (it != map_.begin() && std::prev(it)->second > lo) --it;
        while (it != map_.end() && it->first < hi) {
            long start = it->first, end = it->second;
            it = map_.erase(it);
            if (start < lo) map_.emplace(start, lo);
            if (end > hi) map_.emplace(hi, end);
        }
    }

    // Whether x is in the set: the interval starting at or before x must end after it.
    bool contains(long x) const {
        auto it = map_.upper_bound(x);
        return it != map_.begin() && std::prev(it)->second > x;
    }

    // The intervals in ascending order.
    std::vector<std::pair<long, long>> intervals() const { return {map_.begin(), map_.end()}; }

private:
    std::map<long, long> map_;   // start -> end of disjoint, non-touching [start, end) intervals
};
