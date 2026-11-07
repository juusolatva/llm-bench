Write a C++17 header solution.hpp (no main) with this class:

```cpp
class IntervalSet {
public:
    void add(long lo, long hi);       // add every integer x with lo <= x < hi
    void remove(long lo, long hi);    // remove every integer x with lo <= x < hi
    bool contains(long x) const;
    std::vector<std::pair<long, long>> intervals() const;
};
```

- A default-constructed IntervalSet is empty. add and remove do nothing when lo >= hi.
- intervals() returns the set as half-open [lo, hi) pairs sorted by lo, with no two pairs overlapping or touching: after add(1, 3) and add(3, 5) it returns {{1, 5}}.
- contains must run in O(log n), and add and remove in O(log n) plus O(1) per stored interval they merge or delete, where n is the number of stored intervals.
