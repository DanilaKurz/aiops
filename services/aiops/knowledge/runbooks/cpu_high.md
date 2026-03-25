# CPU High Alert Runbook

CPU spikes are almost always a SYMPTOM, not a root cause.

## Investigation Steps
1. Check which process is consuming CPU (top/htop)
2. Check if there was a recent deployment
3. Check database query latency - unindexed queries cause CPU spikes
4. Check for connection pool exhaustion upstream
5. Check memory - GC pressure causes CPU spikes

## Common Root Causes
- Unindexed database query after schema migration
- Connection pool exhaustion causing retry storms
- Memory leak triggering aggressive garbage collection
