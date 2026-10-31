# -*- coding: utf-8 -*-
"""Adversarial verification for tasks.jsonl.

For every task we hand-write one realistic CORRECT final answer and one
realistic WRONG answer that uses the rejected detour material, then assert:

  * correct matches every must_include regex (any_of semantics) and no
    must_not_include regex;
  * wrong matches at least one must_not_include regex, or fails at least one
    must_include item;
  * every regex compiles;
  * no forbidden word appears in any user message.
"""
import json
import re

FORBIDDEN = ['分支', '支线', 'branch', 'fork', '分叉', 'merge', '合并']


def load_tasks(path='tasks.jsonl'):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


# ---- hand-written answers ------------------------------------------------
ANSWERS = {
    "wri-zh-01": {
        "correct": (
            "Kestrel-DB 4.2 极光（Aurora 版）发布公告\n\n"
            "尊敬的客户：\n\n"
            "我们很高兴地宣布，Kestrel-DB 4.2 极光（Aurora 版）将于 2026 年 11 月 18 日正式发布。"
            "本次版本带来全新的查询加速功能，大幅提升复杂查询的响应速度，帮助您的业务系统更高效地运行。\n\n"
            "本次升级聚焦查询性能的全面提升：借助全新的查询加速能力，报表分析与实时查询将获得显著提速，"
            "为生产环境提供更稳定、更流畅的使用体验。\n\n"
            "我们诚邀您体验新版本带来的性能提升。如需申请试用，请通过官方渠道提交试用申请，"
            "我们的客户团队将尽快与您联系。\n\n"
            "Kestrel-DB 团队"
        ),
        "wrong": (
            "我们很高兴地宣布 Kestrel-DB 4.2「蓝晶」版本（备选代号凌峰）将于 2026 年 11 月 18 日发布，"
            "新增查询加速功能，欢迎申请试用。"
        ),
    },
    "wri-zh-02": {
        "correct": (
            "各位同事：\n\n"
            "为保障系统稳定运行，我们计划于 2026 年 11 月 15 日（周日）14:00–17:00 进行系统维护，共 3 小时。"
            "维护期间，CRM 系统和订单系统将无法登录，预计在 17:30 前恢复正常使用。\n\n"
            "请在维护开始前完成以下准备：保存草稿、导出报表，以免造成数据丢失。给您带来的不便，敬请谅解。\n\n"
            "如有任何疑问，欢迎随时与我们联系。\n\n"
            "平台运维组"
        ),
        "wrong": (
            "各位同事：本周六凌晨我们将进行系统维护，窗口放宽为 4 小时（原定周五 22:00 开始），"
            "期间 CRM 系统和订单系统无法登录，请提前准备。"
        ),
    },
    "wri-zh-03": {
        "correct": (
            "云帆科技 招聘：数据平台工程师\n\n"
            "岗位职责：\n"
            "1. 负责数据平台的日常运维与稳定性保障；\n"
            "2. 参与数据链路与 ETL 流程的优化；\n"
            "3. 与业务团队协作，推动数据产品落地。\n\n"
            "任职要求：计算机相关专业本科及以上学历，熟悉大数据技术栈，具备良好的沟通能力。\n\n"
            "工作地点：深圳。\n\n"
            "薪资待遇：22–32K·14 薪。\n\n"
            "截止日期：2026 年 11 月 30 日。\n\n"
            "请将简历发送至 jobs@yunfan.example。"
        ),
        "wrong": (
            "云帆科技招聘数据平台工程师，工作地点深圳，薪资 25–40K·15 薪（优秀者可面议），"
            "投递邮箱 jobs@yunfan.example，截止 2026 年 11 月 30 日。"
        ),
    },
    "wri-zh-04": {
        "correct": (
            "恒岳资本 2026 年度投资者大会邀请函\n\n"
            "尊敬的机构投资者：\n\n"
            "谨定于 2026 年 12 月 12 日 14:00，在上海浦东云帆中心 3 楼望江厅举办恒岳资本 2026 年度投资者大会。\n\n"
            "本次大会将由恒岳资本首席策略官顾言川先生发表主旨演讲，并围绕宏观经济与市场展望设置议程亮点，"
            "与您共话投资机遇。\n\n"
            "如您有意参会，请于 12 月 5 日前将报名信息发送至 ir@hengyue.example。\n\n"
            "恒岳资本投资者关系部"
        ),
        "wrong": (
            "恒岳资本 2026 年度投资者大会邀请函：本次大会将由知名经济学家沈砚舟先生发表主旨演讲，"
            "并特邀澄川研究院的陆星遥女士参与圆桌讨论，诚邀机构投资者莅临。"
        ),
    },
    "wri-en-01": {
        "correct": (
            "We're thrilled to announce Tideflow Horizon (v2.4), the latest release of our "
            "billing automation platform for small business owners.\n\n"
            "Launching on November 18, 2026, Tideflow Horizon brings smart invoice reconciliation "
            "and automatic late-payment reminders, so you can spend less time chasing paperwork "
            "and more time growing your business.\n\n"
            "With Tideflow, small-business owners get a clear view of every invoice and payment. "
            "Ready to see it in action? Start your free trial today at https://tideflow.example/start."
        ),
        "wrong": (
            "We're excited to announce Tideflow Crestline, our new billing platform for small business owners. "
            "It includes smart invoice reconciliation, and you can sign up at https://tideflow.example/start."
        ),
    },
    "wri-en-02": {
        "correct": (
            "Team,\n\n"
            "We will run a planned outage on Sunday, November 15, 2026, from 2:00–5:00 PM ET "
            "(a 3-hour window). During this time the customer portal and the mobile app will be "
            "unavailable, with service expected to be restored by 5:30 PM ET.\n\n"
            "If anything goes wrong we can roll back quickly, so there is no cause for concern.\n\n"
            "Please tell customers who ask that this is a scheduled maintenance window and that "
            "access will be back shortly.\n\n"
            "Questions? Reach out to Priya Nair (On-call Lead)."
        ),
        "wrong": (
            "Team, we will run the outage on Saturday using a relaxed 4-hour window, starting at "
            "10:00 PM Friday night. The customer portal will be down; reach out to Priya Nair with questions."
        ),
    },
    "wri-en-03": {
        "correct": (
            "Vertex Analytics is hiring a Platform Reliability Engineer in Austin, TX.\n\n"
            "As a Platform Reliability Engineer, you will:\n"
            "- Own the reliability and availability of our data platform.\n"
            "- Build monitoring and incident-response tooling.\n"
            "- Partner with engineering teams to improve on-call and SLO practices.\n\n"
            "What we're looking for: solid experience with cloud infrastructure, Linux, and "
            "observability tooling, plus strong communication skills.\n\n"
            "Salary: $125k–$165k base, plus a 10% performance bonus.\n\n"
            "Application deadline: December 1, 2026.\n\n"
            "To apply, email your resume to apply@vertex-analytics.example."
        ),
        "wrong": (
            "Vertex Analytics is hiring a Platform Reliability Engineer in Austin, TX. "
            "Salary: competitive, with a range up to $180k and a 15% bonus. Deadline December 1, 2026. "
            "Apply at apply@vertex-analytics.example."
        ),
    },
    "wri-en-04": {
        "correct": (
            "Dear institutional investors,\n\n"
            "Halcyon Capital cordially invites you to the 2026 Annual Investor Summit on "
            "December 12, 2026, at 2:00 PM, at the Harborview Ballroom, Meridian Hotel.\n\n"
            "The keynote will be delivered by Julian Reyes, Chief Investment Officer of Halcyon Capital. "
            "The summit will feature agenda highlights including our market outlook and portfolio review.\n\n"
            "To RSVP, please email summit@halcyoncapital.example by December 5, 2026.\n\n"
            "Halcyon Capital Investor Relations"
        ),
        "wrong": (
            "Halcyon Capital's 2026 Annual Investor Summit will feature a keynote by Dr. Elias Marchand, "
            "with Mara Voss joining the afternoon panel. RSVP to summit@halcyoncapital.example."
        ),
    },
}


def item_passes(item, text):
    """any_of semantics: pass if ANY regex matches."""
    return any(re.search(r, text, re.IGNORECASE) for r in item['any_of'])


def main():
    tasks = load_tasks()
    by_id = {t['id']: t for t in tasks}

    assert set(ANSWERS) == set(by_id), (set(ANSWERS) ^ set(by_id))

    failures = []
    rows = []

    for tid in by_id:
        t = by_id[tid]
        correct = ANSWERS[tid]['correct']
        wrong = ANSWERS[tid]['wrong']

        # correct answer: all must_include pass, no must_not_include hit
        missed_mi = [i['id'] for i in t['must_include'] if not item_passes(i, correct)]
        hit_mn = [i['id'] for i in t['must_not_include'] if item_passes(i, correct)]

        # wrong answer: at least one must_not_include hit, or fails a must_include
        hit_mn_wrong = [i['id'] for i in t['must_not_include'] if item_passes(i, wrong)]
        failed_mi_wrong = [i['id'] for i in t['must_include'] if not item_passes(i, wrong)]

        ok = (not missed_mi) and (not hit_mn) and (hit_mn_wrong or failed_mi_wrong)
        if not ok:
            failures.append(tid)

        rows.append((tid, missed_mi, hit_mn, hit_mn_wrong, failed_mi_wrong, ok))

    # forbidden-word check across every user message
    fw_hits = []
    for t in tasks:
        for m in t['main_turns'] + t['detour_turns'] + [t['return_turn']]:
            ml = m.lower()
            for w in FORBIDDEN:
                if w in ml:
                    fw_hits.append((t['id'], w))
    if fw_hits:
        failures.append('FORBIDDEN_WORDS')

    # regex compile check
    compile_errs = []
    for t in tasks:
        for grp in ('must_include', 'must_not_include'):
            for item in t[grp]:
                for r in item['any_of']:
                    try:
                        re.compile(r, re.IGNORECASE)
                    except re.error as e:
                        compile_errs.append((t['id'], item['id'], r, str(e)))
    if compile_errs:
        failures.append('REGEX_COMPILE')

    # ---- summary -----------------------------------------------------
    print("=" * 72)
    print("check_answers.py — adversarial verification summary")
    print("=" * 72)
    for tid, missed_mi, hit_mn, hit_mn_wrong, failed_mi_wrong, ok in rows:
        status = 'PASS' if ok else 'FAIL'
        print(f"[{status}] {tid}")
        if missed_mi:
            print(f"      correct misses must_include: {missed_mi}")
        if hit_mn:
            print(f"      correct hits must_not_include: {hit_mn}")
        if not (hit_mn_wrong or failed_mi_wrong):
            print("      wrong answer neither hits must_not_include nor fails a must_include")
        else:
            print(f"      wrong hits must_not_include: {hit_mn_wrong or '-'}"
                  f" | wrong fails must_include: {failed_mi_wrong or '-'}")

    print("-" * 72)
    print(f"forbidden-word hits: {fw_hits or 'none'}")
    print(f"regex compile errors: {compile_errs or 'none'}")

    # extra regression checks for the specific fixes applied
    print("-" * 72)
    print("regression checks for applied fixes:")
    checks = [
        ("zh-02 four_hour must NOT flag '14时00分'", '14时00分 至 17时00分', by_id['wri-zh-02'],
         'must_not_include', 'four_hour', False),
        ("zh-02 window must match '14时00分 至 17时00分'", '14时00分 至 17时00分', by_id['wri-zh-02'],
         'must_include', 'window', True),
        ("zh-03 salary must match '22K–32K'", '22K–32K·14 薪', by_id['wri-zh-03'],
         'must_include', 'salary', True),
        ("en-02 four_hour must NOT flag '24-hour support'", 'we offer 24-hour support', by_id['wri-en-02'],
         'must_not_include', 'four_hour', False),
        ("en-03 salary must match '$125,000 to $165,000'", '$125,000 to $165,000', by_id['wri-en-03'],
         'must_include', 'salary', True),
        ("en-03 bonus must NOT flag '10% discount'", 'we offer a 10% discount', by_id['wri-en-03'],
         'must_include', 'bonus', False),
        ("en-03 competitive must NOT flag 'competitive benefits'", 'we offer competitive benefits', by_id['wri-en-03'],
         'must_not_include', 'competitive', False),
        ("en-03 competitive must flag 'Salary: competitive'", 'Salary: competitive', by_id['wri-en-03'],
         'must_not_include', 'competitive', True),
    ]
    reg_fail = []
    for label, text, t, grp, iid, expect_match in checks:
        item = next(i for i in t[grp] if i['id'] == iid)
        got = item_passes(item, text)
        ok = got == expect_match
        if not ok:
            reg_fail.append(label)
        print(f"  [{'OK' if ok else 'BAD'}] {label} -> matched={got}")

    print("=" * 72)
    if failures or reg_fail:
        print("RESULT: FAIL", failures, reg_fail)
        raise SystemExit(1)
    print("RESULT: ALL CHECKS PASS")


if __name__ == '__main__':
    main()
