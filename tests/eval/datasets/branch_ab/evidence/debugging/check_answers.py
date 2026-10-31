# -*- coding: utf-8 -*-
"""Adversarial verification for tasks.jsonl grading regexes.

For every task we keep one hand-written CORRECT final answer (realistic, the
way a good assistant would actually write it) and one hand-written WRONG
answer that uses the rejected material. We assert:
  * the correct answer matches every must_include and no must_not_include;
  * the wrong answer matches at least one must_not_include OR fails a must_include;
  * every regex compiles;
  * no forbidden word appears in any user message.
"""
import json
import re
import sys

FORBIDDEN = ["分支", "支线", "branch", "fork", "分叉", "merge", "合并"]

# Hand-written answers, keyed by task id.
CORRECT = {
    "dbg-zh-01": (
        "根因：quantum-sync 模块的 deduct_stock_v2 在重试时未携带幂等键，同一笔 "
        "tx_no 被重复扣减（错误码 NX-4471 即幂等键冲突），导致促销时段对账后出现负库存；"
        "与夜间对账任务重复执行、锁超时无关。修复：仅改 quantum-sync，为重试补充幂等键 "
        "idem_key = tx_no + \"_\" + sku，锁超时保持 500ms。约束遵守：不改数据库 schema、"
        "不新增外部依赖，扣减接口 P99 控制在 400ms 以内，对账错误率压到 0.5% 以下。"
    ),
    "dbg-zh-02": (
        "根因：med-cache 缓存失效事件在高峰期被丢弃，slot-reserve 读到旧号源快照"
        "（stale read），导致同一号源被重复占用；错误码 SLT-9021，与时区问题无关。"
        "修复：仅改 med-cache 与 slot-reserve 两个微服务，缓存 key 加版本号 ver=src_v3，"
        "采用「主动失效 + 双读校验」，TTL 维持 30 秒。约束遵守：不停服、向后兼容旧版客户端、"
        "11 月 3 日前上线、关键路径 P99 不超过 250 毫秒。"
    ),
    "dbg-zh-03": (
        "根因：ledger-core 用 float64 存金额，分转元再转回分时产生舍入误差"
        "（错误码 FPR-1009 即浮点精度丢失），导致跨币种转账差 1 分钱；与网络重试重复记账无关。"
        "修复：仅改 ledger-core，金额改为以「分」为单位的整数存储，中间换算统一走 numbra-decimal，"
        "重试上限维持 3 次。约束遵守：不停机、历史流水可追溯、通过全部 214 条回归用例、"
        "11 月 5 号前上线。"
    ),
    "dbg-zh-04": (
        "根因：scheduler-v9 路径规划中两把锁的获取顺序不一致，一台先拿 lane_lock 再拿 "
        "grid_lock、另一台相反，形成循环等待（错误码 AGV-DLK-55），导致 3 号巷道机器人死锁；"
        "与低电量回充无关。修复：仅改 scheduler-v9，统一锁序为 lane_lock → grid_lock。"
        "约束遵守：不新增传感器硬件、在线滚动发布、单台死锁 20 秒内恢复、兼容 320 台 AGV。"
    ),
    "dbg-en-01": (
        "Root cause: seatmap-core's allocate_seat_v3 reuses a stale allocation token on "
        "retry (BP-SEAT-77 means allocation token missing), so the second attempt reassigns "
        "the same seat; not replica lag. Fix: only seatmap-core — mint a fresh token per "
        "attempt (token = pnr@seat:attempt); the seat lock timeout stays 40ms. Constraints "
        "honored: no downtime for the check-in API, old kiosk clients keep working, "
        "duplicate-pass rate below 0.02%, P99 under 180ms."
    ),
    "dbg-en-02": (
        "Root cause: stream-bridge batches samples in a fixed 200ms window, and the 14:00 "
        "batch job floods it, overflowing the window (TLMT-3310 = telemetry batch window "
        "overflow); not MQTT broker backpressure. Fix: only stream-bridge — make the window "
        "adaptive and spill overflow to a queue (max_spill = 4096); the broker buffer stays "
        "5MB. Constraints honored: no PLC firmware changes, gaps under 0.1%, P95 under 90ms, "
        "rolled out without stopping the line."
    ),
    "dbg-en-03": (
        "Root cause: prorate-core writes the boundary segment twice because seg_end is "
        "inclusive (PRC-8830 = segment boundary overlap); not double-counted days. Fix: only "
        "prorate-core — make seg_end exclusive and recompute charge = base * days / 30 rounded "
        "half-up; the grace period stays 1 day. Constraints honored: no credit-reversal scripts, "
        "all 88 pricing plans keep working, zero overcharge on the next invoice run, invoice "
        "job under 45 minutes."
    ),
    "dbg-en-04": (
        "Root cause: matchmaker-v6 builds a rank histogram with a fixed int16 counter that "
        "overflows when a 5-stack squad with very high ranks queues (MMX-CRASH-19 = rank "
        "histogram integer overflow), crashing the rank-sort routine; not a socket leak. Fix: "
        "only matchmaker-v6 — widen the counter to int64 and clamp the histogram "
        "(max_rank_bin = 30000); the lobby socket limit stays 2048. Constraints honored: no "
        "schema migration on the match table, ship before the Grand Finals on Nov 8, crash "
        "rate back to zero, reconnect under 3 seconds."
    ),
}

WRONG = {
    "dbg-zh-01": (
        "根因是夜间对账任务被重复执行，锁超时太短，日志里打出了 LK-3300。"
        "修复：把对账任务的分布式锁超时从 500ms 放宽到 3000ms，就不会再重复执行、负库存就消失了。"
    ),
    "dbg-zh-02": (
        "根因是预约释放用了 UTC 时间、和本地差 8 小时（告警 ZN-7710），导致号源没及时释放。"
        "修复：把预约锁的 TTL 从 30 秒放宽到 120 秒，重复号源即可解决。"
    ),
    "dbg-zh-03": (
        "根因是网络重试导致同一笔转账被重复记账（错误码 CUR-5502）。"
        "修复：把重试次数上限从 3 次放宽到 8 次，即可避免重复记账。"
    ),
    "dbg-zh-04": (
        "根因是 AGV 低电量自动回充抢占了巷道（告警 BATT-7712）。"
        "修复：把回充阈值从 15% 放宽到 40%，让更多机器人提前回充，死锁即可解除。"
    ),
    "dbg-en-01": (
        "Root cause is replica lag (RPL-2081). Fix: relax the seat lock timeout from 40ms to "
        "900ms and point reads at the primary."
    ),
    "dbg-en-02": (
        "Root cause is MQTT broker backpressure (MQTT-1184). Fix: raise the broker buffer "
        "from 5MB to 60MB."
    ),
    "dbg-en-03": (
        "Root cause is the proration formula double-counting the old plan's days (DAY-9912). "
        "Fix: extend the proration grace period from 1 day to 7 days."
    ),
    "dbg-en-04": (
        "Root cause is the squad lobby leaking a socket per member (LBY-3307). Fix: double "
        "the lobby socket limit from 2048 to 8192."
    ),
}


def match_any(text, patterns):
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


def compile_all(tasks):
    for t in tasks:
        for group in ("must_include", "must_not_include"):
            for item in t[group]:
                for p in item["any_of"]:
                    re.compile(p, re.IGNORECASE)  # raises on bad regex


def main():
    tasks = [json.loads(line) for line in open("tasks.jsonl", encoding="utf-8")]
    by_id = {t["id"]: t for t in tasks}

    errors = []

    # 1. every regex compiles
    try:
        compile_all(tasks)
    except re.error as e:
        errors.append("regex compile error: %s" % e)

    # 2. forbidden words in user messages
    for t in tasks:
        msgs = t["main_turns"] + t["detour_turns"] + [t["return_turn"]]
        for m in msgs:
            low = m.lower()
            for f in FORBIDDEN:
                if f in low:
                    errors.append("%s: forbidden word %r in user message: %s" % (t["id"], f, m[:40]))

    # 3. correct answers pass, wrong answers fail
    rows = []
    for t in tasks:
        tid = t["id"]
        c = CORRECT[tid]
        w = WRONG[tid]

        c_missing = [i["id"] for i in t["must_include"]
                     if not match_any(c, i["any_of"])]
        c_contam = [i["id"] for i in t["must_not_include"]
                    if match_any(c, i["any_of"])]
        w_contam = [i["id"] for i in t["must_not_include"]
                    if match_any(w, i["any_of"])]
        w_missing = [i["id"] for i in t["must_include"]
                     if not match_any(w, i["any_of"])]

        ok_c = (not c_missing) and (not c_contam)
        ok_w = bool(w_contam) or bool(w_missing)

        rows.append((tid, ok_c, ok_w, c_missing, c_contam, w_contam, w_missing))

        if not ok_c:
            if c_missing:
                errors.append("%s: CORRECT answer MISSES must_include %s" % (tid, c_missing))
            if c_contam:
                errors.append("%s: CORRECT answer falsely CONTAMINATED by %s" % (tid, c_contam))
        if not ok_w:
            errors.append("%s: WRONG answer is not caught (no must_not_include hit and "
                          "all must_include present)" % tid)

    # summary table
    print("id           correct  wrong-caught   (correct misses / contam | wrong contam / misses)")
    print("-" * 90)
    for tid, ok_c, ok_w, cm, cc, wc, wm in rows:
        print("%-12s %-8s %-13s misses=%s contam=%s | contam=%s misses=%s"
              % (tid, "PASS" if ok_c else "FAIL", "YES" if ok_w else "NO",
                 cm or "-", cc or "-", wc or "-", wm or "-"))

    print()
    if errors:
        print("FAILURES:")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    print("All checks passed: %d tasks, every correct answer matches all must_include "
          "and no must_not_include; every wrong answer is caught; all regexes compile; "
          "no forbidden words in user messages." % len(tasks))


if __name__ == "__main__":
    main()
