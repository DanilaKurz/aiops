# Bank System Infrastructure Map

## Architecture Overview

Banking microservice system with 4-tier architecture processing financial transactions.

```
[Users] -> [IG01/IG02] -> [Tomcat01-04] -> [MG01/MG02] -> [docker/MySQL/Redis]
            Ingress         App Servers      Middleware       Backend Services
```

## Components

### Tier 1: Ingress Gateway (IG)
| Component | Role | Resources |
|-----------|------|-----------|
| IG01 | Ingress gateway, load balancer | JVM app, CPU+Memory+Disk+Network |
| IG02 | Ingress gateway, load balancer (redundant) | JVM app, CPU+Memory+Disk+Network |

Receives all external traffic, distributes across Tomcat instances.
If IG degrades -> ALL user traffic affected.

### Tier 2: Application Servers (Tomcat)
| Component | Role | Resources |
|-----------|------|-----------|
| Tomcat01 | Application server (JVM) | 86 KPIs: CPU, Disk, HTTP, JVM, Memory, Network |
| Tomcat02 | Application server (JVM) | 86 KPIs |
| Tomcat03 | Application server (JVM) | 83 KPIs |
| Tomcat04 | Application server (JVM) | 86 KPIs |

Process business logic, call middleware. JVM-based -> vulnerable to GC pressure, heap exhaustion.
Symptoms here (busy threads, GC Allocation Failure) usually mean DOWNSTREAM problem.

### Tier 3: Middleware (MG)
| Component | Role | Resources |
|-----------|------|-----------|
| MG01 | Middleware/service bus (JVM) | 83 KPIs: CPU, Disk, HTTP, JVM, Memory, Network |
| MG02 | Middleware/service bus (JVM) | 82 KPIs |

Orchestrates calls between app servers and backend. JVM-based.
Known failure modes: JVM OOM Heap, high JVM CPU load, memory pressure.
MG problems cascade UP to Tomcat and IG.

### Tier 4: Backend Services
| Component | Role | Resources |
|-----------|------|-----------|
| Mysql01 | Primary database | 144 KPIs: CPU, DB (130+ MySQL metrics), Disk, Memory, Network |
| Mysql02 | Secondary database | 150 KPIs |
| Redis01 | Cache/session store | 80 KPIs: CPU, Disk, Memory, Network, Redis (32 metrics) |
| Redis02 | Cache/session store | 76 KPIs |

Databases and caches. Highest KPI density (150 KPIs for Mysql02).
IMPORTANT: MySQL components have MANY KPIs -> they often appear "most anomalous" by count,
but this does NOT mean they are the root cause. Many MySQL metrics move together (Innodb
pending reads, writes, fsyncs all spike simultaneously from a single cause).

### Infrastructure: Docker Containers
| Component | Role | Resources |
|-----------|------|-----------|
| dockerA1 | Container runtime | 6 KPIs: CPU, Memory, Network |
| dockerA2 | Container runtime | 4 KPIs: CPU, Memory |
| dockerB1 | Container runtime | 6 KPIs: CPU, Memory, Network |

Minimal KPIs. Rarely root cause, usually symptom of what runs inside them.

### Virtual Services (Golden Signals)
| Component | Role | Metrics |
|-----------|------|---------|
| ServiceTest1-11 | End-to-end test endpoints | 4 each: rr (request rate), sr (success rate), mrt (mean response time), cnt (count) |

These represent USER-VISIBLE service quality. When sr drops or mrt spikes -> users are impacted.

## Dependency Graph

```
IG01 -----> Tomcat01 -----> MG01 -----> dockerA1
IG01 -----> Tomcat02 -----> MG01 -----> dockerA2
IG01 -----> Tomcat03 -----> MG02 -----> dockerB1
IG01 -----> Tomcat04 -----> MG02 -----> dockerB2
IG02 -----> Tomcat01       (MG01/MG02 also use MySQL and Redis
IG02 -----> Tomcat02        but these edges are not in trace data)
IG02 -----> Tomcat03
IG02 -----> Tomcat04
```

## Causality Rules

1. If MG01/MG02 has MEMORY or JVM problem -> Tomcat threads will block -> IG latency rises
   Root cause = MG, NOT Tomcat or IG
2. If MySQL shows many anomalous KPIs -> check if it's just correlated metrics (Innodb family)
   MySQL has 150 KPIs, many are correlated. 20 anomalous MySQL KPIs may = 1 actual problem
3. If Redis memory is high -> services using cache will slow down
   Root cause = Redis, symptoms appear on Tomcat/MG
4. If ALL components degrade simultaneously -> look for the DEEPEST component (closest to data)
5. Tomcat GC Allocation Failure = symptom of upstream wait, NOT root cause
6. IG anomalies = almost never root cause, always downstream symptom
