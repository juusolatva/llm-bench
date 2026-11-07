Write a C++17 header solution.hpp (no main) with:

```cpp
std::vector<std::string> split(const std::string& s, char delim);
```

It splits s at every occurrence of delim. Empty fields are kept: split("a,,b", ',') is {"a", "", "b"}, split("", ',') is {""} and split(",", ',') is {"", ""}.
