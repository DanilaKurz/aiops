# Database Connection Issues Runbook

## Symptoms
- Connection timeout errors in application logs
- Connection pool exhausted warnings
- Increased latency across dependent services

## Investigation Steps
1. Check db connection count vs pool limit
2. Check for long-running queries (locks)
3. Check if max_connections was recently changed
4. Trace upstream: what is generating excess connections?

## Common Root Causes
- Long-running transactions holding locks
- Missing index causing table scans
- Connection leak in application code
