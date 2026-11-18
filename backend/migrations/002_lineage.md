# Schema v2

`traces.evidence` JSON nullable：每次执行的来源追溯证据（规范JSON，≤64KB）。`level` 为 full（全部行号）/ counts（逐组精确计数）/ summary（全局汇总）；NULL 表示该剖面创建于追溯上线前，界面标明缺少来源。行号为执行快照中 readings/sensors 的1起行号，同键同值重复行各算一份。结果与证据同一事务写入，都落库才标 completed。存量库由 `src/config/migrate.py` 在 backend/worker 启动时幂等 ALTER 补列；新库由 metadata create_all 直接建出。
