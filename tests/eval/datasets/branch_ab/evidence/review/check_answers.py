#!/usr/bin/env python3
"""Adversarial verification of tasks.jsonl grading regexes.

For every task it holds one hand-written CORRECT final answer and one
hand-written WRONG answer that uses the rejected side material, then asserts:

  * the correct answer matches every must_include item and no must_not_include
  * the wrong answer matches at least one must_not_include OR fails a must_include
  * every regex compiles (IGNORECASE)
  * no forbidden word appears in any user message
"""

import json
import re
import sys

FORBIDDEN = ["分支", "支线", "branch", "fork", "分叉", "merge", "合并"]

# One CORRECT final answer per task id (realistic assistant phrasing, natural
# hyphenation where an English reviewer would hyphenate, no rejected material).
CORRECT = {
    "rev-zh-01": (
        "本次 Kestrel-DB 4.2 升级方案审查结论为有条件通过。停机窗口控制在 90 分钟以内"
        "（约 1.5 小时），预算 37 万元需锁定；业务数据保留 7 年、审计日志零丢失作为硬性"
        "验收项。主从复制采用 QuorumSync 参数组，延迟阈值保持 3 秒，并配置 2 秒告警提前量，"
        "超阈值自动告警。上线日期须不晚于 11 月 15 日，回滚与停机方案需再细化。"
    ),
    "rev-zh-02": (
        "换热站改造方案校审结论为有条件通过。预算 82 万元、改造工期 6 天内完成；改造期间"
        "生产停线不超过 4 小时，并保留手工旁路供安全员手动干预。新阀门整定压力 1.6 MPa，"
        "水压试验 2.0 MPa；旁路加装机械锁止手柄，保压时间延长至 45 分钟。"
    ),
    "rev-zh-03": (
        "钱包提现流程改动审查结论为有条件通过。单笔上限维持 5 万元、日累计 20 万元；所有"
        "提现保留二次验证，短信验证码有效期 5 分钟，失败重试不超过 3 次。审计流水字段包含"
        " trace_id 并改为强校验；新增手工冻结开关，命中风控即冻结账户。"
    ),
    "rev-zh-04": (
        "门诊排班系统设计方案评审结论为有条件通过。系统支持 32 个科室、单日排班量上限 "
        "12000 人次；急诊科 24 小时有人值守，护士连续排班不超过 12 小时，换班提前量 48 小时。"
        "排班引擎只做候选建议、保留人工复核，并加入急诊科 0 人值班硬校验。"
    ),
    "rev-en-01": (
        "The gateway change is conditionally approved. Keep the per-key rate limit at 400 rps, "
        "the upstream timeout at 800 ms, the 24-hour idempotency window, and the 3-D Secure step; "
        "carry the x-corr-id header end to end. Add a hard burst ceiling of 600 rps with "
        "backpressure and pin x-corr-id validation to strict mode."
    ),
    "rev-en-02": (
        "The inference pipeline change is conditionally approved. Keep the p95 latency budget at "
        "250 ms and the 6-hour feature refresh; hold the shadow rollout at 10% traffic for two "
        "weeks and keep the Cedar-Base fallback online; maintain the 40 GB warm cache. Add an "
        "auto-warm trigger at 25 GB and a latency kill switch at 300 ms."
    ),
    "rev-en-03": (
        "The firmware change is conditionally approved. Keep the max speed at 1.8 m/s and the "
        "e-stop trigger within 200 ms; retain the 3-meter exclusion radius around the charging bay "
        "and dual-channel braking; keep signed telemetry logs with each robot's unit_id. Add a "
        "cornering speed clamp at 0.9 m/s and a heartbeat watchdog at 50 ms."
    ),
    "rev-en-04": (
        "The retention engine change is conditionally approved. Keep 30-minute unsubscribe "
        "processing, 180-day inactive-account deletion, and 15-minute suppression sync; require a "
        "fresh double opt-in before re-enrollment; watermark every export with the batch_id and "
        "processing date. Add a 90-day stale-draft purge job and a daily consent-audit report."
    ),
}

# One WRONG final answer per task id: it adopts the rejected side material.
WRONG = {
    "rev-zh-01": (
        "方案总体可行，建议迁移高峰时段将主从延迟阈值临时放宽到 30 秒，并启用 DriftGuard "
        "插件自动压制延迟；停机窗口 90 分钟、预算 37 万元均可满足。"
    ),
    "rev-zh-02": (
        "建议把停线时间放宽到 8 小时趁夜班施工，并采用 Overpress-X 智能泄压模块替代手工旁路，"
        "实现全自动响应。"
    ),
    "rev-zh-03": (
        "建议大促期间把单笔上限放宽到 8 万元、日累计 30 万元，并引入 TurboPay 第三方风控加速"
        "组件跳过二次验证。"
    ),
    "rev-zh-04": (
        "建议流感季把护士连续排班放宽到 16 小时，并让 ShiftOptix 自动排班引擎完全替代人工复核。"
    ),
    "rev-en-01": (
        "To keep checkout fast during peak, relax the per-key rate limit to 900 rps and raise the "
        "upstream timeout to 1500 ms, and adopt SwiftMesh to route around 3-D Secure."
    ),
    "rev-en-02": (
        "To cut cost during the trial, shrink the warm cache to 8 GB and switch to a 12-hour feature "
        "refresh, and adopt the QuikScore-Lite model."
    ),
    "rev-en-03": (
        "To hit throughput, raise the max speed to 2.6 m/s and extend the e-stop trigger to 500 ms, "
        "and apply the NavBoost-X patch to route around the exclusion zone."
    ),
    "rev-en-04": (
        "To keep quarterly numbers up, extend inactive-account deletion to a 365-day window and run "
        "unsubscribe processing in 4-hour batches, then adopt ReSpark soft opt-in."
    ),
}


def any_matches(patterns, text):
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def main():
    with open("tasks.jsonl", encoding="utf-8") as f:
        tasks = [json.loads(line) for line in f if line.strip()]

    by_id = {t["id"]: t for t in tasks}
    assert set(by_id) == set(CORRECT) == set(WRONG), (
        f"id mismatch: tasks={sorted(by_id)} correct={sorted(CORRECT)} wrong={sorted(WRONG)}"
    )

    failures = []
    for t in tasks:
        tid = t["id"]
        correct = CORRECT[tid]
        wrong = WRONG[tid]

        # 1. forbidden words in user messages
        user_msgs = list(t["main_turns"]) + list(t["detour_turns"]) + [t["return_turn"]]
        for m in user_msgs:
            for w in FORBIDDEN:
                if w in m:
                    failures.append(f"{tid}: forbidden word {w!r} in user message {m!r}")

        # 2. regexes compile
        for item in t["must_include"] + t["must_not_include"]:
            for p in item["any_of"]:
                try:
                    re.compile(p, re.IGNORECASE)
                except re.error as e:
                    failures.append(f"{tid}: bad regex {p!r}: {e}")

        # 3. correct answer: every must_include matches, no must_not_include matches
        missed = [mi["id"] for mi in t["must_include"] if not any_matches(mi["any_of"], correct)]
        if missed:
            failures.append(f"{tid}: CORRECT answer fails must_include {missed}")
        contaminated = [
            mn["id"] for mn in t["must_not_include"] if any_matches(mn["any_of"], correct)
        ]
        if contaminated:
            failures.append(f"{tid}: CORRECT answer contaminated by {contaminated}")

        # 4. wrong answer: must match a must_not_include OR fail a must_include
        wrong_hit_mn = [
            mn["id"] for mn in t["must_not_include"] if any_matches(mn["any_of"], wrong)
        ]
        wrong_miss_mi = [
            mi["id"] for mi in t["must_include"] if not any_matches(mi["any_of"], wrong)
        ]
        if not wrong_hit_mn and not wrong_miss_mi:
            failures.append(
                f"{tid}: WRONG answer is not caught (no must_not_include hit, no must_include miss)"
            )

    if failures:
        print("FAILURES:")
        for x in failures:
            print("  -", x)
        sys.exit(1)

    # Summary table
    print(f"{'task':10} {'mi':>2} {'mn':>2}  correct  wrong-caught")
    for t in tasks:
        tid = t["id"]
        correct = CORRECT[tid]
        wrong = WRONG[tid]
        mi_ok = all(any_matches(mi["any_of"], correct) for mi in t["must_include"])
        mn_ok = not any(any_matches(mn["any_of"], correct) for mn in t["must_not_include"])
        wrong_hit_mn = [
            mn["id"] for mn in t["must_not_include"] if any_matches(mn["any_of"], wrong)
        ]
        wrong_miss_mi = [
            mi["id"] for mi in t["must_include"] if not any_matches(mi["any_of"], wrong)
        ]
        caught = ",".join(wrong_hit_mn) or ("miss:" + ",".join(wrong_miss_mi))
        print(
            f"{tid:10} {len(t['must_include']):>2} {len(t['must_not_include']):>2}  "
            f"{'OK' if (mi_ok and mn_ok) else 'BAD':<5}  {caught}"
        )

    print(
        f"\nAll {len(tasks)} tasks pass: correct answers satisfy all must_include and no "
        "must_not_include; wrong answers are caught; regexes compile; no forbidden words."
    )


if __name__ == "__main__":
    main()
