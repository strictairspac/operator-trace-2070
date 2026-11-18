# gb-4105 验证报告 · 剖面输出分组来源追溯

日期：2026-11-18。环境：python3.11（venv `/tmp/gb4105/venv`，SQLite 代 PostgreSQL、fakeredis 代队列）、node22+jsdom。四套共 **82 项全部通过**。

## 需求 → 实现 → 验证

| 需求 | 实现 | 验证 |
|---|---|---|
| 剖面页点开任意输出分组，翻查计入的采样/传感器原始行号 | `GET /traces/{id}/lineage?row&cursor&limit`；results 页输出分组表 + 侧栏面板 | api: 追溯接口200/条目序号连续；frontend: 打开渲染50条 |
| 同键同值重复行各算一份 | 血缘按快照行号记录，不按值去重 | engine/api: 3条相同readings×2个相同sensors → 6条 `[1,1,2,2,3,3]×[1,2,1,2,1,2]` |
| 追溯容量限64KB | 证据规范JSON ≤65536字节（自报bytes，fixpoint实测） | engine: 三级容量均不超限、字节数自报准确 |
| 超出可降级查询，来源仍要查全 | full→counts→summary 逐级降级；各级 totals/逐组计数精确，checksum 锚定完整血缘 | engine/api: 10000条场景 counts/summary 计数精确、提示"来源已完整扫描" |
| 翻页不重跑整份计划 | 证据随执行落库，翻页只读 `traces.evidence` | api: 3页游标合并与单页取全逐字节一致 |
| 翻页中断后恢复到原位置 | 不透明游标（base64url JSON offset）+ 面板位置存 sessionStorage | api: 游标恢复 offset=50；frontend: 关闭重开直接请求 cur-50 |
| 重试不改换行号或顺序 | 证据不可变；前端重试重放失败请求的同一游标（修复了重试用错游标的缺陷） | api: 同游标两次请求逐字节相同；frontend: 失败后重试仍取 cur-100 |
| 源表改动/算子升级后仍按该次执行解释 | 证据执行时从快照计算并不可变落库；`version:1` | api: PUT 修改数据集后追溯响应逐字节不变；engine: 重跑 checksum 一致 |
| 结果和证据都存好才标完成；写入失败标记失败 | worker 单事务写 result+evidence+status | api: 正常完成两者俱在；注入提交失败 → failed 且无部分结果 |
| 旧剖面照常打开，标明缺少来源 | `evidence` 可空；NULL → `level:missing` 200 响应 + 页面徽标"缺少来源" | api: 详情/导出/追溯均正常；smoke: 旧剖面徽标 |
| 热键跨页 | 面板打开时 ←/→ 翻页、Esc 关闭，输入框聚焦不劫持 | frontend: → 跨页取数、末页不多发请求、← 回退 |
| 源表改动后的复查 | 同上不可变性 | api 通过 |

另：旧库迁移（`src/config/migrate.py` 幂等补列，backend/worker 启动执行）、viewer 只读可查、匿名401、非法游标400、越界分组404、未完成409、`execute()` 与改动前实现逐字段一致（剔除耗时）。

## 复跑

```sh
/tmp/gb4105/venv/bin/python verify_engine.py   # 18
/tmp/gb4105/venv/bin/python verify_api.py      # 28（每次重建 /tmp/gb4105/verify.db）
node verify_frontend.mjs                       # 15（需先 npm install，已装 jsdom）
node verify_smoke.mjs                          # 21
```

## 备注
- 本环境无 docker/postgres/redis，API 级验证用 SQLite+fakeredis 替身；迁移代码走 SQLAlchemy inspector，方言无关，PostgreSQL 下为 `ALTER TABLE traces ADD COLUMN evidence JSON`。
- 验证脚本与报告按项目惯例放在 `test-artifacts/gb-4105`，不进源码树。
