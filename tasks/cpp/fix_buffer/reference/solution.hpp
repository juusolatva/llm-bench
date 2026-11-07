#pragma once
#include <cstddef>
#include <cstring>
#include <utility>

class Buffer {
public:
    explicit Buffer(std::size_t size) : size_(size), data_(new char[size]) {
        std::memset(data_, 0, size_);
    }
    Buffer(const Buffer& other) : size_(other.size_), data_(new char[other.size_]) {
        std::memcpy(data_, other.data_, size_);
    }
    Buffer(Buffer&& other) noexcept
        : size_(std::exchange(other.size_, 0)), data_(std::exchange(other.data_, nullptr)) {}
    Buffer& operator=(const Buffer& other) {
        if (this != &other) {
            Buffer copy(other);
            swap(copy);
        }
        return *this;
    }
    Buffer& operator=(Buffer&& other) noexcept {
        if (this != &other) {
            delete[] data_;
            size_ = std::exchange(other.size_, 0);
            data_ = std::exchange(other.data_, nullptr);
        }
        return *this;
    }
    ~Buffer() { delete[] data_; }
    std::size_t size() const { return size_; }
    char& operator[](std::size_t i) { return data_[i]; }
    const char& operator[](std::size_t i) const { return data_[i]; }
    char* data() { return data_; }
private:
    void swap(Buffer& other) noexcept {
        std::swap(size_, other.size_);
        std::swap(data_, other.data_);
    }
    std::size_t size_;
    char* data_;
};
