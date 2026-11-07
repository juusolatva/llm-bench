Write Go code in `package solution` (standard library only, no main, no tests) with:

```go
func NewHandler() http.Handler
```

It returns an HTTP handler for a small in-memory key-value store:
- `PUT /kv/{key}` stores the request body as the value of key (overwriting any old value) and responds 204 No Content.
- `GET /kv/{key}` responds 200 with the stored value as the body, or 404 if the key does not exist.
- `DELETE /kv/{key}` deletes the key and responds 204, or 404 if the key does not exist.
- Any other method on `/kv/{key}` responds 405 Method Not Allowed.
- key is the non-empty path segment after `/kv/` (no further `/`). Every other path responds 404.
- Every NewHandler() call has its own empty store. The handler is called concurrently from many goroutines.
