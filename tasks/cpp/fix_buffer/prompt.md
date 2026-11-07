Copying or assigning a Buffer from this solution.hpp crashes the program. Fix the class so that copies are independent deep copies, copy assignment works (including self-assignment), and moving a Buffer transfers ownership of its memory without copying the data (a moved-from Buffer has size() 0). Keep the existing public interface. Reply with the complete fixed solution.hpp.

```cpp
#pragma once
#include <cstddef>
#include <cstring>

class Buffer {
public:
    explicit Buffer(std::size_t size) : size_(size), data_(new char[size]) {
        std::memset(data_, 0, size_);
    }
    ~Buffer() { delete data_; }
    std::size_t size() const { return size_; }
    char& operator[](std::size_t i) { return data_[i]; }
    const char& operator[](std::size_t i) const { return data_[i]; }
    char* data() { return data_; }
private:
    std::size_t size_;
    char* data_;
};
```
