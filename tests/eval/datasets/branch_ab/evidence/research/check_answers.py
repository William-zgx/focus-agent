# -*- coding: utf-8 -*-
"""Adversarial verification of the fixed tasks.jsonl.

For every task we keep one hand-written CORRECT final answer (realistic,
what a good assistant would actually write) and one hand-written WRONG
answer that carries over the rejected material.  We assert:

  * every regex compiles (with IGNORECASE),
  * no forbidden word appears in any user message,
  * the CORRECT answer matches every must_include and no must_not_include,
  * the WRONG answer matches >=1 must_not_include OR fails >=1 must_include.
"""

import json
import re

TASKS_PATH = "tasks.jsonl"
FORBIDDEN = ["分支", "支线", "branch", "fork", "分叉", "merge", "合并"]

with open(TASKS_PATH, encoding="utf-8") as f:
    TASKS = [json.loads(line) for line in f if line.strip()]

ANSWERS = {
    "res-zh-01": {
        "correct": (
            "最终选型：紫杉缓存 Pro 2.8，采用单机写 + 异步复制到只读副本的架构。"
            "逐项核对最初约束：① 全年预算 37 万元以内——报价 29.8 万元/年，符合；"
            "② P99 延迟低于 2 毫秒——实测 1.4 毫秒，符合；"
            "③ 数据全部留在境内、不出海——采用境内部署，符合；"
            "④ 支持 SSD 持久化——具备；"
            "⑤ 至少 3 个只读副本——生产环境配置 3 个只读副本，符合。"
            "关键指标：P99 1.4 毫秒，报价 29.8 万元/年。"
            "备选 Kestrel-Cache 4.2 集群版因主备切换存在缺陷风险，已排除，不予采用。"
        ),
        "wrong": (
            "最终选型：Kestrel-Cache 4.2 集群版，主备切换零丢失。"
            "预算临时放宽到 50 万元，报价 48.8 万元/年，P99 1.4 毫秒，"
            "境内部署、SSD 持久化，3 个只读副本。"
        ),
    },
    "res-zh-02": {
        "correct": (
            "最终选型：辰星报表 5.0。逐项核对：① 总预算 45 万元——报价 31.5 万元，符合；"
            "② 实时刷新低于 5 秒——实测 3.8 秒，符合；"
            "③ 通过 JDBC 直连 MES 系统——支持；"
            "④ 报表导出 PDF 带中文水印——支持；"
            "⑤ 私有化部署——支持，不含任何云端激活依赖。"
            "备选 LumenDash 3.1 因存在云端激活机制已排除。"
        ),
        "wrong": (
            "最终选型：LumenDash 3.1 私有版，报价 42.6 万元，预算可放宽到 52 万元。"
            "激活错误码 LDS-0440 已解决，实时刷新 3.8 秒，JDBC 直连 MES，PDF 中文水印。"
        ),
    },
    "res-zh-03": {
        "correct": (
            "最终采购方案：数策数据 2026Q4 版。逐项核对：① 数据量至少 80 万条——本方案 90 万条，符合；"
            "② 全人工三级标注——满足；"
            "③ 授权完整、可以商用——满足；"
            "④ 交货期不超过 45 天——38 天交货，符合；"
            "⑤ 总预算 28 万元——报价 26.4 万元，符合。"
            "备选语料坊因授权不完整已排除。"
        ),
        "wrong": (
            "最终采购方案：语料坊，报价 19.8 万元，90 万条，"
            "90% 人工标注 + 10% 机器预标（标注等级已松绑），授权编号 AU-7712，"
            "其中 12,400 条来自未授权爬取，交货 38 天。"
        ),
    },
    "res-zh-04": {
        "correct": (
            "最终选型：极光直播云 3.0。逐项核对：① 首屏加载不超过 3 秒——实测 2.1 秒，符合；"
            "② 每月带宽成本不超过 15 万元——报价 14.6 万元/月，符合；"
            "③ 原生支持 WebRTC 低延迟——满足；"
            "④ 防盗链——齐全；"
            "⑤ SLA 不低于 99.95%——实测 99.98%，符合。"
            "备选星速云因非原生 WebRTC 且存在安全漏洞已排除。"
        ),
        "wrong": (
            "最终选型：星速云，报价 12.8 万元/月，实测推流延迟 8.6 秒，"
            "改用 HLS 方案（原生 WebRTC 已松绑），防盗链漏洞 LK-8813 已修复，"
            "首屏 2.1 秒，SLA 99.98%。"
        ),
    },
    "res-en-01": {
        "correct": (
            "Final recommendation: RiverFlow 4.1. Checking each original constraint: "
            "(1) at least 120,000 events per second — RiverFlow measures 132,000 events/sec, satisfied; "
            "(2) end-to-end P99 latency under 900 ms — measured 720 ms, satisfied; "
            "(3) exactly-once semantics — provided without failover caveats; "
            "(4) plugs into our Kafka 3.x cluster — supports Kafka 3.4; "
            "(5) permissive licensing — Apache-2.0. "
            "FalconStream 2.3 was ruled out because its exactly-once guarantee breaks under broker failover."
        ),
        "wrong": (
            "Final recommendation: FalconStream 2.3. It benchmarks at 180,000 events per second, "
            "P99 latency 720 ms, and under broker failover we accept at-least-once semantics "
            "(ticket FLC-9021 is acceptable for us). Kafka 3.x compatible, permissive license."
        ),
    },
    "res-en-02": {
        "correct": (
            "Final procurement recommendation: LexiCorpus 2026-10. Checking each constraint: "
            "(1) at least 500,000 contract clauses — this dataset has 560,000 clauses; "
            "(2) three-pass human annotation — yes; "
            "(3) full commercial license with a documented rights chain — yes; "
            "(4) delivery within 60 days — 47 days; "
            "(5) budget of 140,000 USD — price is 132,000 USD; "
            "(6) coverage of at least 9 jurisdictions — yes. "
            "CorpusWorks was ruled out because parts of its data were scraped without licensing."
        ),
        "wrong": (
            "Final recommendation: CorpusWorks. It costs only 89,000 USD, provides 560,000 clauses "
            "with machine pre-annotation (92% human), delivery in 47 days, and its rights chain is "
            "documented under contract ID CW-4419. Note: 8,400 clauses were scraped but are included."
        ),
    },
    "res-en-03": {
        "correct": (
            "Final recommendation: Meridian Pay 2.0. Checking each constraint: "
            "(1) processing fee no higher than 1.9% — Meridian charges 1.85%, satisfied; "
            "(2) settlement within T+1 — Meridian settles T+1, satisfied; "
            "(3) support for all 24 currencies — yes; "
            "(4) PCI DSS Level 1 certification — yes; "
            "(5) 99.99% uptime SLA — Meridian provides 99.995%, satisfied; "
            "(6) multi-currency settlement to our bank account — yes. "
            "PayVane was ruled out because of slower settlement and lower PCI certification."
        ),
        "wrong": (
            "Final recommendation: PayVane. It charges only 1.2% per transaction, and we accept "
            "settlement at T+3 (relaxing the T+1 requirement). It is PCI DSS Level 2 certified, "
            "and incident PV-3380 is closed. Supports 24 currencies, 99.995% SLA."
        ),
    },
    "res-en-04": {
        "correct": (
            "Final recommendation: Atlas BareMetal 5.0. Checking each constraint: "
            "(1) presence in at least 3 regions — Atlas covers us-east, eu-west, and ap-south, satisfied; "
            "(2) 99.95% uptime SLA — Atlas provides 99.97%, satisfied; "
            "(3) DDoS protection included — yes; "
            "(4) hardware replacement within 48 hours — Atlas replaces within 4 hours, satisfied; "
            "(5) monthly budget of 22,000 USD — Atlas costs 20,400 USD/month, satisfied; "
            "(6) 10 Gbps network interfaces on every box — yes. "
            "RackHaven was ruled out because its real SLA and replacement record fell short."
        ),
        "wrong": (
            "Final recommendation: RackHaven. It quotes 14,500 USD per month; we relax the uptime "
            "requirement to 99.9% and accept that a failed box took 96 hours to replace during "
            "incident RH-7702. It covers 3 regions, has DDoS protection, and 10 Gbps NICs."
        ),
    },
}


def compile_all(tasks):
    for t in tasks:
        for item in t["must_include"] + t["must_not_include"]:
            for r in item["any_of"]:
                re.compile(r, re.IGNORECASE)


def user_messages(t):
    return list(t["main_turns"]) + list(t["detour_turns"]) + [t["return_turn"]]


def check_forbidden(tasks):
    bad = []
    for t in tasks:
        for msg in user_messages(t):
            for w in FORBIDDEN:
                if w in msg:
                    bad.append((t["id"], w, msg[:60]))
    return bad


def item_matches(item, text):
    return any(re.search(r, text, re.IGNORECASE) for r in item["any_of"])


def main():
    # 1. compile
    compile_all(TASKS)

    # 2. forbidden words
    bad = check_forbidden(TASKS)
    assert not bad, f"forbidden words in user messages: {bad}"

    ids = {t["id"] for t in TASKS}
    assert ids == set(ANSWERS), f"answer coverage mismatch: {ids ^ set(ANSWERS)}"

    failures = []
    for t in TASKS:
        tid = t["id"]
        correct = ANSWERS[tid]["correct"]
        wrong = ANSWERS[tid]["wrong"]

        mi_failed = [i["id"] for i in t["must_include"] if not item_matches(i, correct)]
        mni_hit = [i["id"] for i in t["must_not_include"] if item_matches(i, correct)]

        wrong_mni = [i["id"] for i in t["must_not_include"] if item_matches(i, wrong)]
        wrong_mi_failed = [i["id"] for i in t["must_include"] if not item_matches(i, wrong)]
        wrong_flagged = len(wrong_mni) > 0 or len(wrong_mi_failed) > 0

        ok = (not mi_failed) and (not mni_hit) and wrong_flagged
        print(
            f"{tid}: correct_ok={ok} "
            f"(must_include_missed={mi_failed or '-'}, must_not_hit={mni_hit or '-'}) "
            f"| wrong_flagged={wrong_flagged} (mni_hit={wrong_mni or '-'}, mi_missed={wrong_mi_failed or '-'})"
        )
        if not ok:
            failures.append(tid)

    assert not failures, f"failures: {failures}"
    print(f"\nALL {len(TASKS)} TASKS PASS.")


if __name__ == "__main__":
    main()
