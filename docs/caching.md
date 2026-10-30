# Price cache (Redis) — design and decision log

Market prices from Yahoo Finance are cached in Redis, so screens that ask for
the same prices again don't wait for yfinance.

## Summary

| | |
|---|---|
| **Problem** | Every Holdings, Analytics and summary request fetched every price from yfinance again, one symbol at a time. About 95% of the backend's time was spent waiting for Yahoo. |
| **Approach** | Check Redis before each yfinance call; on a miss, fetch and save the result with a TTL. Only valid prices are saved. |
| **Where** | `market_data_service.py` only. The services, routers and frontend didn't change. |
| **Effect** | A repeated round of every screen went from 43 yfinance calls and ~2.7–3.0 s to **0 calls and 0.31 s** (about 9x faster). The first visit after the cache expires is only slightly faster (see [Measurements](#measurements)). |
| **Optional** | Without `REDIS_URL`, or with Redis down, every lookup goes to yfinance as before. CI and the tests run with the cache off. |
| **Main limits** | Prices can be up to 5 min (current) or 1 h (history) old; history keys are per portfolio, so they are rarely shared between users. |

## How it works

```
service ──asyncio.to_thread──▶ get_current_stock_price("AAPL")
                                 │
                                 ├─ empty ticker? → ValueError (never cached)
                                 ├─ Redis GET prices:v1:current:AAPL
                                 │     hit  → return it (~1 ms)
                                 │     miss / Redis error → continue
                                 ├─ yfinance history(period="5d")
                                 ├─ checks (data, Close column, finite, > 0) → ValueError (never cached)
                                 └─ Redis SET ... EX 300 → return price
```

`get_historical_stock_prices` follows the same steps with its own key and a 1 h TTL.

### Keys and TTLs

| Data | Key | TTL | Setting |
|---|---|---|---|
| Current price | `prices:v1:current:AAPL` | 5 min | `ttl_price_cache_current_prices_seconds` (300) |
| Daily closes | `prices:v1:historical:AAPL:<start>:<end>` | 1 h | `ttl_price_cache_historical_prices_seconds` (3600) |

- The symbol is stripped and uppercased, so `" aapl "` and `"AAPL"` share a key. Dates are ISO, and `end` is exclusive, as yfinance takes it.
- `v1` is the format version. If the stored format changes, bump it: the old keys are never read again and expire on their own.
- Keys contain no user or portfolio id. Prices are public data, so every user shares them.
- Nothing deletes keys: they only expire (TTL), get evicted when Redis is full, or are removed by hand (`FLUSHDB`). Adding or deleting a transaction doesn't need to clear anything, because the cache holds only prices.

### Files

| File | Role |
|---|---|
| `backend/app/db/redis_client.py` | One `redis_client` per process, created on import like the database engine; `None` without `REDIS_URL`. 1 s connect and socket timeouts. |
| `backend/app/services/price_cache.py` | Key builders, `fetch_*_from_cache` and `cache_*`. Every `redis.RedisError` becomes a warning in the log plus a miss. |
| `backend/app/services/market_data_service.py` | Reads the cache after the empty-ticker check; writes only after every check passed. |
| `backend/app/main.py` | Closes the client on shutdown (lifespan). |
| `backend/tests/service_tests/test_price_cache.py` | The cache module on its own (14 tests). |
| `backend/tests/service_tests/test_market_data_service.py` | "Price cache" section: how the price functions use the cache (9 tests). |
| `backend/benchmarks/measure_price_calls.py` | Counts and times yfinance calls per screen (see [Measurements](#measurements)). |

### Setup

Redis 8 runs in Docker, next to the Postgres container:

```bash
docker run -d --name stock-platform-redis -p 127.0.0.1:6380:6379 \
  --restart unless-stopped redis:8 \
  redis-server --maxmemory 100mb --maxmemory-policy allkeys-lru
```

```
# backend/app/.env
REDIS_URL=redis://127.0.0.1:6380/0
# Defaults: TTL_PRICE_CACHE_CURRENT_PRICES_SECONDS=300, TTL_PRICE_CACHE_HISTORICAL_PRICES_SECONDS=3600
```

The host port is 6380 because an unrelated Redis installed with apt already listens on 6379 in WSL. With `allkeys-lru`, when the 100 MB limit is reached Redis evicts the least recently used keys instead of refusing writes, which suits a cache. Persistence is Redis's default (RDB snapshots, no AOF): keys usually survive a container restart, and losing them only costs a refetch.

## Decisions

| Decision | Why | Alternatives considered |
|---|---|---|
| **Redis** | The user wanted to learn it. It is shared by every backend process and survives backend restarts. | A dict in memory with timestamps: simpler, but per process and lost on every reload of `fastapi dev`. |
| **Cache inside `market_data_service.py`, sync client** | The price functions are already sync and run in `asyncio.to_thread`, so a sync client fits. No service, router or test patch point changed. | An async client used from the services: every call site would change. |
| **One client per process, created on import** | The client holds its own connection pool and is safe to share between threads, like the SQLAlchemy engine. | A client per request, like `get_db`: pointless, a Redis client has no transaction or per-request state. A client in the lifespan + `Depends`: every call site would change. |
| **TTL 5 min current, 1 h history** | A current price is the last close and can move during market hours; past closes don't change. | Shorter TTLs (fewer hits); a long TTL for history ranges that end before today (see [Next steps](#next-steps)). |
| **Only valid results are cached** | A failed lookup (unknown ticker, Yahoo down) is retried on the next request instead of being stuck for the TTL. | Caching failures briefly ("negative caching"): fewer calls for bad tickers, but a Yahoo outage would stick. |
| **Redis errors = miss + warning, 1 s timeouts** | The cache must never break a price lookup. A stopped container costs at most ~1 s per lookup, then yfinance answers. | Failing the request: the app would depend on Redis being up. |
| **Histories stored as JSON with `double_precision=15`** | `to_json` keeps 10 decimals by default, so `384.2799987792969` came back as `384.2799987793`. With 15 the closes come back exactly. Read with `read_json(StringIO(...), typ="series")`: pandas reads a plain string as a file path, and returns a DataFrame by default. | Pickle: exact, but unsafe to load and tied to the pandas version. |
| **`set(key, value, ex=ttl)`** | `setex` is deprecated in redis-py 8. | — |
| **Tests use `fakeredis`; `conftest.py` sets `REDIS_URL=""`** | No real Redis in CI. Before the empty URL, local test runs saved fake prices (`AAPL = 150.0`) into the real Redis and the next run read them back and failed. | A Redis container in CI: more realistic, not needed for this logic. |

## Measurements

`backend/benchmarks/measure_price_calls.py` runs the real app in-process against Postgres and real yfinance, as the owner of one portfolio. Each round replays the Holdings tab, the Analytics tab (4 requests, "3M" period), the AI summary (fake LLM, prices only) and the ticker check of an add-transaction. Round 2 repeats round 1 right away. It counts every call **our app** makes to `Ticker.history()`, so a cache hit shows up as a missing call.

Portfolio 1, 6 symbols. Baseline: two runs on 2026-10-26, no cache. Redis: one run on 2026-10-28, cache emptied with `FLUSHDB` first.

| Screen | Baseline round 1 | Baseline round 2 | Redis round 1 | Redis round 2 |
|---|---|---|---|---|
| Holdings | 6 calls, 1.30–1.43 s | 6 calls, 0.32 s | 6 calls, 1.67 s | **0 calls, 0.02 s** |
| Analytics | 24 calls, 2.49–2.62 s | 24 calls, 1.46–1.73 s | 11 calls, 2.42 s | **0 calls, 0.18 s** |
| AI summary (prices) | 12 calls, 0.77–0.83 s | 12 calls, 0.84–0.88 s | 0 calls, 0.11 s | 0 calls, 0.11 s |
| Ticker check | 1 call, 0.05–0.06 s | 1 call, 0.05–0.06 s | 0 calls, 0.00 s | 0 calls, 0.00 s |
| **Round total** | **43 calls, 4.68–4.87 s** | **43 calls, 2.67–2.99 s** | **17 calls, 4.20 s** | **0 calls, 0.31 s** |

Single lookups, measured on 2026-10-27: current price 0.56 s → 0.001 s from the cache, history 0.85 s → 0.006 s.

**Reading the numbers**

- **Warm cache: ~9x faster.** A repeated round drops from 2.7–3.0 s to 0.31 s and makes no yfinance calls. The remaining 0.31 s is database queries, our calculations and the Redis reads: prices are no longer the bottleneck.
- **Empty cache: only ~10–15% faster.** Round 1 still makes 17 calls (6 current prices, 11 histories), all misses that cost Yahoo's time. Round 1 also includes the ~1 s yfinance spends setting up its session on the first call of a process. The 26 calls saved are the repeats between screens, explained below.
- **One Redis run against a baseline from two days earlier.** Yahoo's speed varies from day to day (the Redis run's Holdings round 1 was slower than the baseline's). The call counts are exact; the seconds are indicative.

### Which screens share prices

| Screen | Needs | With an empty cache, after the screens above it |
|---|---|---|
| Holdings | 6 current prices | all misses |
| Analytics `/distribution`, `/unrealized_gains_distribution` | the same 6 current prices | all hits (cached by Holdings) |
| Analytics `/performance` | 6 histories | all misses |
| Analytics `/stocks_performance` | 6 histories, one range per symbol | 5 misses, 1 hit |
| AI summary | 6 current prices + 6 histories | all hits |
| Ticker check | 1 current price | hit |

A history's range starts at the **first transaction date minus 7 days** and ends tomorrow, whatever period is shown. That is why the summary's 365-day performance reuses the keys of the chart's 3-month one. `/stocks_performance` builds each symbol's range from that symbol's own first transaction, so only the symbol whose first transaction is also the portfolio's first reuses a key.

### More users

Current-price keys have no user in them, so the number of current-price calls to Yahoo depends on how many **different symbols** are asked for per 5 minutes, not on how many users there are: one user pays the wait, the others read it from Redis. This also keeps the app under Yahoo's request limits as it grows. History keys don't spread like that: they depend on each portfolio's first transaction date, so two users holding the same stock usually get different keys.

### Reproducing

Run from `Portfolio-Analytics/` with Postgres and Redis started:

```bash
redis-cli -p 6380 ping                    # PONG, or the run silently measures yfinance only
redis-cli -p 6380 FLUSHDB                 # start round 1 with an empty cache
uv run python backend/benchmarks/measure_price_calls.py --portfolio-id 1 --label redis
REDIS_URL= uv run python backend/benchmarks/measure_price_calls.py --portfolio-id 1 --label baseline   # cache off
```

An environment variable overrides `app/.env`, so `REDIS_URL=` (empty) turns the cache off for that run. Each results file records `price_cache` (`on`, `off`, or `down` when Redis doesn't answer). The 2026-10-28 file predates that field; it was run with the cache on.

## Watching the cache

```bash
redis-cli -p 6380 MONITOR                       # every command live: GET on each lookup, SET after a miss
redis-cli -p 6380 --scan --pattern 'prices:*'   # keys currently stored
redis-cli -p 6380 TTL prices:v1:current:AAPL    # seconds left (-2 = gone)
redis-cli -p 6380 INFO stats | grep keyspace    # keyspace_hits / keyspace_misses since Redis started
```

In `MONITOR`, a `GET` followed by a `SET` on the same key is a miss; a `GET` alone is a hit. Warnings such as `Redis read failed for prices:v1:current:AAPL` in the backend log mean Redis is unreachable and the lookup went to yfinance.

## Known limitations

- **Cache stampede.** Two requests that miss the same key at the same moment both call yfinance and both save the price. Harmless with few users: the same value is written twice. With many users, a popular key expiring could send a burst of calls; the usual fix is a short lock so only one request fetches (`SET lock:... NX EX 10`) while the others wait.
- **Chart and donuts can disagree slightly.** During market hours the history's "today" close can be up to 1 h old, while current prices are at most 5 min old. So the Analytics return chart and the allocation donuts / Holdings table can show slightly different values for today.
- **History keys are per portfolio.** See [More users](#more-users).
- **No hit/miss metrics in the app.** Hits are seen with `MONITOR` / `INFO stats` or inferred from the benchmark's missing calls; nothing is logged per hit.
- **Redis has no password.** It is bound to `127.0.0.1`, which is fine locally. Add a password (or ACL user) to `REDIS_URL` when deploying.
- **Symbols are still fetched one at a time** on a miss (see [Next steps](#next-steps)).

## Next steps

- **Fetch symbols in parallel** (deferred on 2026-10-28, the user's decision: too many changes for now). `market_data_service.py` stays sync. `asyncio.gather` goes over the existing `to_thread` calls at 5 call sites, with a semaphore (for example 5 calls at once) in async code:
  - `HoldingService` current prices, with `return_exceptions=True` so a failure still gives `None` fields;
  - `AnalyticService` distribution and unrealized gains, plain `gather`;
  - `_build_performance_series` histories, plain `gather`;
  - `get_stock_performances`, gathered per symbol with `return_exceptions=True` to keep `errors`.

  Not `ticker_validation` (one ticker). Never gather database calls (one shared `AsyncSession`). This only speeds up misses: with a warm cache there is nothing left to wait for.
- **Share histories across portfolios.** Cache one range per symbol (for example from a fixed early date to today) and slice the needed dates in Python, so the key is just the symbol.
- **Long TTL for history ranges that end before today**, since past closes never change.
- **Stampede lock**, if the app gets many users.
