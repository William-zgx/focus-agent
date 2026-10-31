# 分支工作流 A/B 实验：进度（2026-10-31，已暂停）

目标：用配对实验证明（或证伪）“分支工作流在长任务上比线性对话结果更好”。
线性组：主线、岔开的问题、回到主线全部发在一个线程。分支组：岔开的问题在
fork 出的子分支里做，合并提案经批准后导入主线，再在主线回答。只给“回到主线”
这一轮的回答打分。

## 已完成
- `scripts/branch_ab/run_experiment.py`：每个 (任务, 组, 重复) 独立进程 + 独立临时状态目录；
  记录每次模型调用的完整输入。关闭分支推荐、branch decision、委派、联网搜索、embedding。
- `scripts/branch_ab/score.py`：正则检查（must_include / must_not_include）+ 盲评 LLM 评委
  （只看用户消息与最终回答，不知道组别）。
- `scripts/branch_ab/analyze.py`：按 (任务, 重复) 配对；差值、任务级聚类 bootstrap 95% CI、
  符号检验、pass^1 / pass^k。
- 可用模型（2026-10-31 实测）：`deepseek:deepseek-v4-pro`、`moonshot:kimi-k2.6`、
  `openai:deepseek-v4-pro` 可用；OpenRouter key 已过期；`mimo:mimo-v2.5-pro` 报不支持的模型。
- 用 `dev-task.jsonl`（1 个手写任务）跑通全链路，n=1，不作结论。

## 试跑观察（待验证的假设，未改代码）
- 合并提案把用户在分支里已拍板的决定写成“仅为分支内待批准结论、尚未验证”；
  主线回答因此拒绝给最终建议（评委 2/5），线性组直接给出正确答案（5/5）。
- 同一导入结论在主线 prompt 中出现三次：`Approved branch conclusions` 区块、
  `<memory-context>`（confidence 显示 0.00）、导入结论 system 消息。

## 下一步
1. 冻结 32 个任务（研究/调试/写作/审查 各 8，中英各半），放在
   `tests/eval/datasets/branch_ab/tasks.jsonl`；由不看实现的独立作者编写（上次中途停止，未产出文件）。
2. 基线：DeepSeek V4 Pro，32 × 2 组 × 3 次 = 192 次运行；Kimi K2.6 盲评。
3. 基线冻结后，再按失败分类修复，并用同一任务集复测。

## 运行命令
```bash
.venv/bin/python scripts/branch_ab/run_experiment.py --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
  --model deepseek:deepseek-v4-pro --repeats 3 --workers 6 --out reports/branch_ab/deepseek
.venv/bin/python scripts/branch_ab/score.py --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
  --runs reports/branch_ab/deepseek --judge moonshot:kimi-k2.6
.venv/bin/python scripts/branch_ab/analyze.py reports/branch_ab/deepseek/scores.*.jsonl --by category --by language
```
