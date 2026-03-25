# Network Partition Runbook

## Symptoms
- Intermittent connection timeouts between services
- Increased latency on cross-service calls
- Some requests succeed, others fail

## Investigation Steps
1. Check trace data for inter-service latency spikes
2. Compare affected vs unaffected service pairs
3. Check if affected services share a network segment
4. Look for DNS resolution failures

## Common Root Causes
- Switch/router failure in specific rack
- DNS misconfiguration after deployment
- Security group / firewall rule change
