Write a C++17 header solution.hpp (no main) with this class template:

```cpp
template <typename K, typename V>
class LruCache {
public:
    explicit LruCache(std::size_t capacity);  // capacity >= 1
    std::optional<V> get(const K& key);       // the value, and key becomes the most recently used; std::nullopt if absent
    void put(const K& key, const V& value);   // insert or update; key becomes the most recently used;
                                              // if size() would exceed capacity, evict the least recently used key
    std::size_t size() const;
};
```

get and put must run in O(1) on average. K works with std::hash and ==.
