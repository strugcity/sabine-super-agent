# Sabine Super Agent - Load Test Suite

This directory contains Locust-based load tests for validating the Sabine Super Agent API performance targets.

## PRD Exit Criteria

The load test suite validates: **&quot;Load test confirms 10-15s latency at P95.&quot;**

### Target Metrics

| Endpoint | P95 Target | Description |
|----------|------------|-------------|
| `/invoke` | &lt; 15,000ms | Full agent invocation with LLM reasoning |
| `/invoke/cached` | &lt; 10,000ms | Cached agent invocation (faster) |
| `/health` | &lt; 500ms | Health check endpoint |
| `/tools` | &lt; 1,000ms | List available tools |
| `/wal/stats` | &lt; 1,000ms | WAL statistics |
| `/metrics/prometheus` | &lt; 500ms | Prometheus metrics |
| `/api/skills/gaps` | &lt; 1,000ms | Skill gaps listing |

## Prerequisites

Install Locust:

```bash
pip install locust
```

Or add to your `requirements.txt` if not already present.

## Usage

### Quick Start (Headless Mode)

For CI/CD pipelines or automated testing:

```bash
BASE_URL=http://localhost:8000 API_KEY=your-api-key locust -f tests/load/locustfile.py --headless -u 5 -r 1 --run-time 60s
```

**Parameters:**
- `-u 5`: Spawn 5 concurrent users
- `-r 1`: Spawn rate of 1 user per second
- `--run-time 60s`: Run for 60 seconds

### Web UI Mode

For interactive testing and real-time monitoring:

```bash
BASE_URL=http://localhost:8000 API_KEY=your-api-key locust -f tests/load/locustfile.py
```

Then open http://localhost:8089 in your browser to:
- Configure number of users and spawn rate
- Start/stop tests dynamically
- View real-time charts and statistics
- Download detailed reports

## Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `BASE_URL` | API server base URL | `http://localhost:8000` | No |
| `API_KEY` | API key for authenticated endpoints | None | Yes (for protected endpoints) |

### Task Distribution

The load test simulates realistic user behavior with weighted task distribution:

| Task | Weight | Frequency | Notes |
|------|--------|-----------|-------|
| `health_check` | 3 | High | Monitoring systems poll frequently |
| `list_tools` | 3 | High | Lightweight read operation |
| `prometheus_metrics` | 3 | High | Metrics collection |
| `invoke_cached` | 2 | Medium | Cached agent calls |
| `wal_stats` | 2 | Medium | Administrative queries |
| `invoke_agent` | 1 | Low | Most expensive operation |
| `skill_gaps_list` | 1 | Low | Administrative queries |

## Interpreting Results

### Success Criteria

✅ **Pass:** All endpoint P95 latencies meet target thresholds  
❌ **Fail:** Any endpoint exceeds its P95 target

### Example Output

```
Name                          # reqs      # fails  |     Avg     Min     Max  Median  |   req/s
-----------------------------------------------------------------------------------------
GET /health                      450     0(0.00%)  |     120      45     380     110  |    7.50
POST /invoke                     150     0(0.00%)  |   12500    8900   14200   12000  |    2.50
POST /invoke/cached              300     0(0.00%)  |    8200    6100    9800    8000  |    5.00
GET /tools                       450     0(0.00%)  |     250     120     520     230  |    7.50
GET /wal/stats                   300     0(0.00%)  |     380     180     680     360  |    5.00
GET /metrics/prometheus          450     0(0.00%)  |     150      60     340     140  |    7.50
GET /skills/gaps                 150     0(0.00%)  |     420     200     780     400  |    2.50
-----------------------------------------------------------------------------------------
Aggregated                      2250     0(0.00%)  |    2288      45   14200     250  |   37.50

Percentage of requests that completed within X ms
Name                          # reqs    50%    66%    75%    80%    90%    95%    98%    99%  99.9% 99.99%   100%
-----------------------------------------------------------------------------------------
GET /health                      450    110    130    150    170    220    280    350    370    380    380    380
POST /invoke                     150  12000  12500  13000  13200  13800  14100  14200  14200  14200  14200  14200
```

### Key Metrics to Monitor

1. **P95 Latency**: 95th percentile response time (main target)
2. **Error Rate**: Should be 0% for stable operations
3. **Requests/Second**: Throughput under load
4. **Response Time Distribution**: Check for outliers

## User Count Guidance

Sabine is a **personal agent**, not a high-traffic public API:

- **1-3 users**: Normal single-user usage patterns
- **5-10 users**: Testing concurrent family members or multiple sessions
- **10+ users**: Stress testing (not expected in production)

Start with 1-5 users for realistic load testing.

## Troubleshooting

### Issue: Connection refused

**Solution:** Ensure the FastAPI server is running:

```bash
python lib/agent/server.py
# Or:
uvicorn lib.agent.server:app --host 0.0.0.0 --port 8000
```

### Issue: 401 Unauthorized

**Solution:** Provide valid API key:

```bash
API_KEY=your-actual-api-key locust -f tests/load/locustfile.py --headless -u 1 -r 1 --run-time 10s
```

### Issue: Import errors

**Solution:** Install Locust:

```bash
pip install locust
```

### Issue: High latency on `/invoke`

**Expected:** `/invoke` is an expensive operation (LLM reasoning). P95 &lt; 15s is acceptable.  
**Action:** Monitor token usage and consider caching strategies.

## Integration with CI/CD

Example GitHub Actions workflow snippet:

```yaml
- name: Run Load Tests
  run: |
    BASE_URL=http://localhost:8000 API_KEY=${{ secrets.API_KEY }} \
    locust -f tests/load/locustfile.py --headless -u 5 -r 1 --run-time 60s
  env:
    API_KEY: ${{ secrets.SABINE_API_KEY }}
```

## Additional Resources

- [Locust Documentation](https://docs.locust.io/)
- [PRD Exit Criteria](../../docs/)
- [API Documentation](../../README.md)
