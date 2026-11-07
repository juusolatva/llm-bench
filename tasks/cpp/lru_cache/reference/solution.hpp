#pragma once
#include <cstddef>
#include <list>
#include <optional>
#include <unordered_map>
#include <utility>

template <typename K, typename V>
class LruCache {
public:
    explicit LruCache(std::size_t capacity) : capacity_(capacity) {}

    std::optional<V> get(const K& key) {
        auto it = index_.find(key);
        if (it == index_.end()) return std::nullopt;
        order_.splice(order_.begin(), order_, it->second);
        return it->second->second;
    }

    void put(const K& key, const V& value) {
        auto it = index_.find(key);
        if (it != index_.end()) {
            it->second->second = value;
            order_.splice(order_.begin(), order_, it->second);
            return;
        }
        order_.emplace_front(key, value);
        index_[key] = order_.begin();
        if (order_.size() > capacity_) {
            index_.erase(order_.back().first);
            order_.pop_back();
        }
    }

    std::size_t size() const { return order_.size(); }

private:
    std::size_t capacity_;
    std::list<std::pair<K, V>> order_;
    std::unordered_map<K, typename std::list<std::pair<K, V>>::iterator> index_;
};
