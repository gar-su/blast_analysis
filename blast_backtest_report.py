#!/usr/bin/env python3
"""炸量广告回测报告生成器"""

import csv
import sys
from datetime import datetime

def load_data(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def print_section(title: str):
    print()
    print("=" * 90)
    print(f"  {title}")
    print("=" * 90)


def report_overall(rows: list[dict]):
    total_pre_cost = sum(float(r["pre_cost"]) for r in rows)
    total_post_cost = sum(float(r["post_cost"]) for r in rows)
    total_pre_rev = sum(float(r["pre_rechargeAmount"]) for r in rows)
    total_post_rev = sum(float(r["post_rechargeAmount"]) for r in rows)
    total_pre_users = sum(int(r["pre_totalNormalUserCnt"]) for r in rows)
    total_post_users = sum(int(r["post_totalNormalUserCnt"]) for r in rows)
    total_pre_pay = sum(int(r["pre_belongPayCnt"]) for r in rows)
    total_post_pay = sum(int(r["post_belongPayCnt"]) for r in rows)

    pre_cpi = total_pre_cost / total_pre_users if total_pre_users else 0
    post_cpi = total_post_cost / total_post_users if total_post_users else 0
    pre_roi = total_pre_rev / total_pre_cost * 100 if total_pre_cost else 0
    post_roi = total_post_rev / total_post_cost * 100 if total_post_cost else 0
    pre_pr = total_pre_pay / total_pre_users * 100 if total_pre_users else 0
    post_pr = total_post_pay / total_post_users * 100 if total_post_users else 0

    print()
    print(f"  {'指标':>10s} | {'炸量前':>12s} | {'炸量后':>12s} | {'变化':>12s}")
    print(f"  {'-'*10}-+-{'-'*12}-+-{'-'*12}-+-{'-'*12}")
    print(f"  {'消耗':>10s} | ${total_pre_cost:>11,.2f} | ${total_post_cost:>11,.2f} | {'':>12s}")
    print(f"  {'回收':>10s} | ${total_pre_rev:>11,.2f} | ${total_post_rev:>11,.2f} | {'':>12s}")
    print(f"  {'用户':>10s} | {total_pre_users:>12,} | {total_post_users:>12,} | {total_post_users - total_pre_users:>+12,}")
    print(f"  {'付费用户':>10s} | {total_pre_pay:>12,} | {total_post_pay:>12,} | {total_post_pay - total_pre_pay:>+12,}")
    print(f"  {'CPI':>10s} | ${pre_cpi:>11.2f} | ${post_cpi:>11.2f} | ${post_cpi - pre_cpi:>+11.2f}")
    print(f"  {'ROI':>10s} | {pre_roi:>11.1f}% | {post_roi:>11.1f}% | {post_roi - pre_roi:>+11.1f}pp")
    print(f"  {'付费率':>10s} | {pre_pr:>11.1f}% | {post_pr:>11.1f}% | {post_pr - pre_pr:>+11.1f}pp")
    print()
    print(f"  样本数: {len(rows)}")


def report_roi_stratification(rows: list[dict]):
    meaningful = [r for r in rows if float(r["pre_cost"]) > 0 and float(r["post_cost"]) > 0]

    # By pre_ROI bracket
    brackets = [
        ("0-30%", 0, 30),
        ("30-60%", 30, 60),
        ("60-100%", 60, 100),
        ("100-200%", 100, 200),
        ("200%+", 200, float("inf")),
    ]
    print()
    print(f"  {'炸前ROI':>12s} | {'样本数':>8s} | {'炸前ROI均':>10s} | {'炸后ROI均':>10s} | {'ROI变化':>10s} | {'改善':>6s} | {'恶化':>6s}")
    print(f"  {'-'*12}-+-{'-'*8}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*6}-+-{'-'*6}")

    for label, lo, hi in brackets:
        bucket = [r for r in meaningful if lo <= float(r["pre_ROI_pct"]) < hi]
        if not bucket:
            continue
        pre_avg = sum(float(r["pre_ROI_pct"]) for r in bucket) / len(bucket)
        post_avg = sum(float(r["post_ROI_pct"]) for r in bucket) / len(bucket)
        change = post_avg - pre_avg
        improved = sum(1 for r in bucket if float(r["post_ROI_pct"]) > float(r["pre_ROI_pct"]))
        worsened = sum(1 for r in bucket if float(r["post_ROI_pct"]) < float(r["pre_ROI_pct"]))
        print(f"  {label:>12s} | {len(bucket):>8d} | {pre_avg:>9.1f}% | {post_avg:>9.1f}% | {change:>+9.1f}pp | {improved:>6d} | {worsened:>6d}")

    # Summary
    all_pre = [float(r["pre_ROI_pct"]) for r in meaningful]
    all_post = [float(r["post_ROI_pct"]) for r in meaningful]
    improved = sum(1 for r in meaningful if float(r["post_ROI_pct"]) > float(r["pre_ROI_pct"]))
    worsened = sum(1 for r in meaningful if float(r["post_ROI_pct"]) < float(r["pre_ROI_pct"]))
    unchanged = len(meaningful) - improved - worsened
    print(f"  {'-'*12}-+-{'-'*8}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*6}-+-{'-'*6}")
    print(f"  {'合计':>12s} | {len(meaningful):>8d} | {sum(all_pre)/len(all_pre):>9.1f}% | {sum(all_post)/len(all_post):>9.1f}% | {(sum(all_post)/len(all_post) - sum(all_pre)/len(all_pre)):>+9.1f}pp | {improved:>6d} | {worsened:>6d}")
    print()
    print(f"  改善: {improved} ({improved/len(meaningful)*100:.1f}%) | 恶化: {worsened} ({worsened/len(meaningful)*100:.1f}%) | 不变: {unchanged} ({unchanged/len(meaningful)*100:.1f}%)")


def report_user_scale_stratification(rows: list[dict]):
    meaningful = [r for r in rows if float(r["pre_cost"]) > 0 and float(r["post_cost"]) > 0]

    brackets = [
        ("0-5", 0, 5),
        ("5-20", 5, 20),
        ("20-50", 20, 50),
        ("50-100", 50, 100),
        ("100+", 100, float("inf")),
    ]
    print()
    print(f"  {'炸前用户':>12s} | {'样本数':>8s} | {'炸前ROI均':>10s} | {'炸后ROI均':>10s} | {'ROI变化':>10s} | {'炸前CPI':>9s} | {'炸后CPI':>9s}")
    print(f"  {'-'*12}-+-{'-'*8}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*9}-+-{'-'*9}")

    for label, lo, hi in brackets:
        bucket = [r for r in meaningful if lo <= int(r["pre_totalNormalUserCnt"]) < hi]
        if not bucket:
            continue
        pre_roi_avg = sum(float(r["pre_ROI_pct"]) for r in bucket) / len(bucket)
        post_roi_avg = sum(float(r["post_ROI_pct"]) for r in bucket) / len(bucket)
        change = post_roi_avg - pre_roi_avg
        pre_cpi = sum(float(r["pre_cost"]) for r in bucket) / sum(int(r["pre_totalNormalUserCnt"]) for r in bucket) if sum(int(r["pre_totalNormalUserCnt"]) for r in bucket) else 0
        post_cpi = sum(float(r["post_cost"]) for r in bucket) / sum(int(r["post_totalNormalUserCnt"]) for r in bucket) if sum(int(r["post_totalNormalUserCnt"]) for r in bucket) else 0
        print(f"  {label:>12s} | {len(bucket):>8d} | {pre_roi_avg:>9.1f}% | {post_roi_avg:>9.1f}% | {change:>+9.1f}pp | ${pre_cpi:>8.2f} | ${post_cpi:>8.2f}")


def report_loss_control(rows: list[dict]):
    """Section 8+9: 盈利最大化分析 + 控损规则 (break-even ROI=40%)"""
    meaningful = [r for r in rows if float(r["pre_cost"]) > 0 and float(r["post_cost"]) > 0]

    def _profit(r):
        return float(r["post_rechargeAmount"]) - 0.4 * float(r["post_cost"])

    # --- Section 8: Overall profitability ---
    total_post_c = sum(float(r["post_cost"]) for r in meaningful)
    total_post_r = sum(float(r["post_rechargeAmount"]) for r in meaningful)
    total_profit = total_post_r - 0.4 * total_post_c
    prof_ads = [r for r in meaningful if _profit(r) > 0]
    loss_ads = [r for r in meaningful if _profit(r) <= 0]
    prof_sum = sum(_profit(r) for r in prof_ads)
    loss_sum = sum(_profit(r) for r in loss_ads)

    print()
    print(f"  --- 整体盈利状况 (盈亏平衡 ROI=40%) ---")
    print(f"  {'炸后总消耗':>20s}: ${total_post_c:>12,.2f}")
    print(f"  {'炸后总回收':>20s}: ${total_post_r:>12,.2f}")
    print(f"  {'炸后整体ROI':>20s}: {total_post_r/total_post_c*100:>11.1f}%")
    print(f"  {'总盈利(rev-0.4*cost)':>20s}: ${total_profit:>+12,.2f}")
    print(f"  {'盈利广告(ROI>=40%)':>20s}: {len(prof_ads)}/{len(meaningful)} ({len(prof_ads)/len(meaningful)*100:.1f}%) -> +${prof_sum:,.2f}")
    print(f"  {'亏损广告(ROI<40%)':>20s}: {len(loss_ads)}/{len(meaningful)} ({len(loss_ads)/len(meaningful)*100:.1f}%) -> -${abs(loss_sum):,.2f}")

    # Profitability by cost bracket
    print()
    print(f"  --- 各消耗段盈利能力 ---")
    print(f"  {'消耗段':>10s} | {'样本':>6s} | {'总盈利':>10s} | {'平均盈利/广告':>11s} | {'炸后ROI':>8s} | {'盈利率':>7s}")
    print(f"  {'-'*10}-+-{'-'*6}-+-{'-'*10}-+-{'-'*11}-+-{'-'*8}-+-{'-'*7}")
    for lo, hi, label in [(0,30,'$0-30'),(30,60,'$30-60'),(60,100,'$60-100'),(100,200,'$100-200'),(200,300,'$200-300'),(300,500,'$300-500'),(500,99999,'$500+')]:
        bucket = [r for r in meaningful if lo <= float(r["pre_cost"]) < hi]
        if not bucket:
            continue
        post_c = sum(float(r["post_cost"]) for r in bucket)
        post_r = sum(float(r["post_rechargeAmount"]) for r in bucket)
        p = post_r - 0.4 * post_c
        roi = post_r / post_c * 100 if post_c else 0
        prof_cnt = sum(1 for r in bucket if _profit(r) > 0)
        avg = p / len(bucket)
        flag = " ***" if p > 0 else ""
        print(f"  {label:>10s} | {len(bucket):>6d} | ${p:>9,.0f} | ${avg:>10.2f} | {roi:>7.1f}% | {prof_cnt/len(bucket)*100:>6.1f}%{flag}")

    # 2D decision matrix
    print()
    print(f"  --- 双维度决策矩阵 (消耗 x 炸前ROI) ---")
    print(f"  {'消耗\\ROI':>10s} | {'0-30%':>25s} | {'30-60%':>25s} | {'60-100%':>25s} | {'100-200%':>25s}")
    print(f"  {'-'*10}-+-{'-'*25}-+-{'-'*25}-+-{'-'*25}-+-{'-'*25}")
    for cost_lo, cost_hi, cost_label in [(0,30,'$0-30'),(30,60,'$30-60'),(60,100,'$60-100'),(100,150,'$100-150'),(150,200,'$150-200'),(200,300,'$200-300'),(300,500,'$300-500')]:
        line = f"  {cost_label:>10s} |"
        for roi_lo, roi_hi in [(0,30),(30,60),(60,100),(100,200)]:
            sub = [r for r in meaningful if cost_lo <= float(r["pre_cost"]) < cost_hi and roi_lo <= float(r["pre_ROI_pct"]) < roi_hi]
            if len(sub) < 3:
                line += f" {'':>25s} |"
            else:
                post_c = sum(float(r["post_cost"]) for r in sub)
                post_r = sum(float(r["post_rechargeAmount"]) for r in sub)
                p = post_r - 0.4 * post_c
                roi = post_r / post_c * 100 if post_c else 0
                line += f" {len(sub):>3d} {roi:>5.0f}% ${p:>8,.0f}  {'':>5s}|"
        print(line)

    # --- Section 9: Control rules ---
    print()
    print(f"  --- 控损规则: $100 <= 消耗 < $300 ---")

    keep = [r for r in meaningful if 100 <= float(r["pre_cost"]) < 300]
    reject = [r for r in meaningful if not (100 <= float(r["pre_cost"]) < 300)]
    k_post_c = sum(float(r["post_cost"]) for r in keep)
    k_post_r = sum(float(r["post_rechargeAmount"]) for r in keep)
    k_profit = k_post_r - 0.4 * k_post_c
    k_roi = k_post_r / k_post_c * 100 if k_post_c else 0
    k_pre_c = sum(float(r["pre_cost"]) for r in keep)
    k_pre_r = sum(float(r["pre_rechargeAmount"]) for r in keep)
    k_prof_cnt = sum(1 for r in keep if _profit(r) > 0)
    k_zero = sum(1 for r in keep if float(r["post_rechargeAmount"]) == 0)

    r_post_c = sum(float(r["post_cost"]) for r in reject)
    r_post_r = sum(float(r["post_rechargeAmount"]) for r in reject)
    r_profit = r_post_r - 0.4 * r_post_c
    r_pre_c = sum(float(r["pre_cost"]) for r in reject)
    avoided = -r_profit if r_profit < 0 else 0

    print(f"  {'指标':>20s} | {'保留组 (执行炸量)':>20s} | {'拒绝组 (不炸)':>20s}")
    print(f"  {'-'*20}-+-{'-'*20}-+-{'-'*20}")
    print(f"  {'样本':>20s} | {len(keep):>19d} ({len(keep)/len(meaningful)*100:.1f}%) | {len(reject):>19d} ({len(reject)/len(meaningful)*100:.1f}%)")
    print(f"  {'炸前消耗':>20s} | ${k_pre_c:>18,.0f} | ${r_pre_c:>18,.0f}")
    print(f"  {'炸后消耗':>20s} | ${k_post_c:>18,.0f} | ${r_post_c:>18,.0f}")
    print(f"  {'炸前ROI':>20s} | {k_pre_r/k_pre_c*100:>19.1f}% | {'':>20s}")
    print(f"  {'炸后ROI':>20s} | {k_roi:>19.1f}% | {r_post_r/r_post_c*100 if r_post_c else 0:>19.1f}%")
    print(f"  {'总盈利':>20s} | ${k_profit:>+18,.0f} | ${r_profit:>+18,.0f}")
    print(f"  {'盈利率':>20s} | {k_prof_cnt/len(keep)*100:>19.1f}% | {'':>20s}")
    print(f"  {'零回收率':>20s} | {k_zero/len(keep)*100:>19.1f}% | {'':>20s}")
    print(f"  {'规则避免损失':>20s} | {'':>20s} | ${avoided:>18,.0f}")

    # Within-window ROI breakdown
    print()
    print(f"  --- 窗口内 ($100-300) 按炸前ROI细分 ---")
    print(f"  {'炸前ROI':>12s} | {'样本':>6s} | {'总盈利':>10s} | {'炸后ROI':>8s} | {'盈利率':>7s}")
    print(f"  {'-'*12}-+-{'-'*6}-+-{'-'*10}-+-{'-'*8}-+-{'-'*7}")
    for lo, hi, label in [(0,30,'0-30%'),(30,60,'30-60%'),(60,100,'60-100%'),(100,200,'100-200%')]:
        sub = [r for r in keep if lo <= float(r["pre_ROI_pct"]) < hi]
        if len(sub) < 3:
            continue
        post_c = sum(float(r["post_cost"]) for r in sub)
        post_r = sum(float(r["post_rechargeAmount"]) for r in sub)
        p = post_r - 0.4 * post_c
        roi = post_r / post_c * 100 if post_c else 0
        prof_cnt = sum(1 for r in sub if _profit(r) > 0)
        print(f"  {label:>12s} | {len(sub):>6d} | ${p:>9,.0f} | {roi:>7.1f}% | {prof_cnt/len(sub)*100:>6.1f}%")

    # Expansion attempts
    print()
    print(f"  --- 扩展规则验证（均导致亏损） ---")
    print(f"  {'扩展方向':>16s} | {'规则':>35s} | {'样本':>6s} | {'总盈利':>10s}")
    print(f"  {'-'*16}-+-{'-'*35}-+-{'-'*6}-+-{'-'*10}")
    expansions = [
        ("当前最优", "$100 <= 消耗 < $300", lambda r: 100 <= float(r["pre_cost"]) < 300),
        ("向下扩展到$60", "$60 <= 消耗 < $300", lambda r: 60 <= float(r["pre_cost"]) < 300),
        ("向上扩展到$500", "$100 <= 消耗 < $500", lambda r: 100 <= float(r["pre_cost"]) < 500),
        ("双向扩展", "$60 <= 消耗 < $500", lambda r: 60 <= float(r["pre_cost"]) < 500),
    ]
    for direction, label, cond in expansions:
        bucket = [r for r in meaningful if cond(r)]
        post_c = sum(float(r["post_cost"]) for r in bucket)
        post_r = sum(float(r["post_rechargeAmount"]) for r in bucket)
        p = post_r - 0.4 * post_c
        flag = " *** 盈利" if p > 0 else " 亏损"
        print(f"  {direction:>16s} | {label:>35s} | {len(bucket):>6d} | ${p:>9,.0f}{flag}")

    print()
    print("  --- 自动关停规则 (伪代码) ---")
    print("  def should_blast(campaign):")
    print("      if 100 <= campaign.pre_cost < 300:")
    print("          return True   # 执行炸量")
    print("      else:")
    print("          return False  # 关停 / 不参与")


def report_zero_recovery(rows: list[dict]):
    """Analyze campaigns with $0 post-blast recharge."""
    meaningful = [r for r in rows if float(r["pre_cost"]) > 0 and float(r["post_cost"]) > 0]
    zero = [r for r in meaningful if float(r["post_rechargeAmount"]) == 0]
    nonzero = [r for r in meaningful if float(r["post_rechargeAmount"]) > 0]

    n = len(meaningful)
    nz = len(zero)
    z_post_c = sum(float(r["post_cost"]) for r in zero)
    z_pre_c = sum(float(r["pre_cost"]) for r in zero)
    z_pre_r = sum(float(r["pre_rechargeAmount"]) for r in zero)
    z_pre_roi = z_pre_r / z_pre_c * 100 if z_pre_c > 0 else 0

    print()
    print(f"  {'零回收样本':>20s}: {nz}/{n} ({nz/n*100:.1f}%)")
    print(f"  {'零回收炸前消耗':>20s}: ${z_pre_c:>11,.0f}")
    print(f"  {'零回收炸后消耗':>20s}: ${z_post_c:>11,.0f}  ← 白烧")
    print(f"  {'零回收炸前回收':>20s}: ${z_pre_r:>11,.0f}")
    print(f"  {'零回收炸前ROI':>20s}: {z_pre_roi:>11.1f}%")

    # By cost bracket
    print()
    print(f"  {'消耗段':>10s} | {'零回收':>6s} | {'该段样本':>7s} | {'零回收率':>7s} | {'零回收炸后消耗':>12s}")
    print(f"  {'-'*10}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}-+-{'-'*12}")
    for lo, hi, label in [(0,30,'$0-30'),(30,60,'$30-60'),(60,100,'$60-100'),(100,200,'$100-200'),(200,300,'$200-300'),(300,500,'$300-500'),(500,99999,'$500+')]:
        bucket = [r for r in meaningful if lo <= float(r["pre_cost"]) < hi]
        if not bucket:
            continue
        z_in = [r for r in bucket if float(r["post_rechargeAmount"]) == 0]
        z_pc = sum(float(r["post_cost"]) for r in z_in)
        print(f"  {label:>10s} | {len(z_in):>6d} | {len(bucket):>7d} | {len(z_in)/len(bucket)*100:>6.1f}% | ${z_pc:>11,.0f}")

    # By user scale
    print()
    print(f"  {'炸前用户':>10s} | {'零回收':>6s} | {'该段样本':>7s} | {'零回收率':>7s}")
    print(f"  {'-'*10}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}")
    for lo, hi, label in [(0,5,'0-5'),(5,20,'5-20'),(20,50,'20-50'),(50,100,'50-100'),(100,99999,'100+')]:
        bucket = [r for r in meaningful if lo <= int(r["pre_totalNormalUserCnt"]) < hi]
        if not bucket:
            continue
        z_in = [r for r in bucket if float(r["post_rechargeAmount"]) == 0]
        print(f"  {label:>10s} | {len(z_in):>6d} | {len(bucket):>7d} | {len(z_in)/len(bucket)*100:>6.1f}%")

    # By pre-ROI bracket
    print()
    print(f"  {'炸前ROI':>10s} | {'零回收':>6s} | {'该段样本':>7s} | {'零回收率':>7s}")
    print(f"  {'-'*10}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}")
    for lo, hi, label in [(0,30,'0-30%'),(30,60,'30-60%'),(60,100,'60-100%'),(100,200,'100-200%'),(200,9999,'200%+')]:
        bucket = [r for r in meaningful if lo <= float(r["pre_ROI_pct"]) < hi]
        if not bucket:
            continue
        z_in = [r for r in bucket if float(r["post_rechargeAmount"]) == 0]
        print(f"  {label:>10s} | {len(z_in):>6d} | {len(bucket):>7d} | {len(z_in)/len(bucket)*100:>6.1f}%")

    # Median comparison
    print()
    print(f"  {'':>10s} | {'pre_cost中位':>12s} | {'pre_users中位':>13s} | {'pre_ROI中位':>12s}")
    print(f"  {'-'*10}-+-{'-'*12}-+-{'-'*13}-+-{'-'*12}")
    for tag, subset in [("零回收", zero), ("有回收", nonzero)]:
        costs = sorted(float(r["pre_cost"]) for r in subset)
        users = sorted(int(r["pre_totalNormalUserCnt"]) for r in subset)
        rois = sorted(float(r["pre_ROI_pct"]) for r in subset)
        m = len(costs) // 2
        print(f"  {tag:>10s} | ${costs[m]:>11.2f} | {users[m]:>12d} | {rois[m]:>11.1f}%")


def report_top_cases(rows: list[dict], n: int = 15):
    meaningful = [r for r in rows if float(r["pre_cost"]) > 0 and float(r["post_cost"]) > 0]
    print()
    print(f"  {'campaign_id':>22s} | {'blast_time':>19s} | {'炸前CPI':>8s} {'炸前ROI':>8s} | {'炸后CPI':>8s} {'炸后ROI':>8s} | {'ROI变化':>8s} | 广告名称")
    print(f"  {'-'*22}-+-{'-'*19}-+-{'-'*8}-{'-'*8}-+-{'-'*8}-{'-'*8}-+-{'-'*8}-+-{'-'*40}")

    # Best and worst by ROI change
    sorted_by_change = sorted(meaningful, key=lambda r: float(r["post_ROI_pct"]) - float(r["pre_ROI_pct"]))
    worst = sorted_by_change[:n]
    best = sorted_by_change[-n:]

    print()
    print(f"  --- ROI 恶化最严重的 {n} 个 ---")
    for r in worst:
        change = float(r["post_ROI_pct"]) - float(r["pre_ROI_pct"])
        print(f"  {r['campaign_id']:>22s} | {r['blast_time']:>19s} | ${float(r['pre_CPI']):>7.2f} {float(r['pre_ROI_pct']):>7.1f}% | ${float(r['post_CPI']):>7.2f} {float(r['post_ROI_pct']):>7.1f}% | {change:>+7.1f}pp | {r['campaign_name'][:40]}")

    print()
    print(f"  --- ROI 改善最显著的 {n} 个 ---")
    for r in reversed(best):
        change = float(r["post_ROI_pct"]) - float(r["pre_ROI_pct"])
        print(f"  {r['campaign_id']:>22s} | {r['blast_time']:>19s} | ${float(r['pre_CPI']):>7.2f} {float(r['pre_ROI_pct']):>7.1f}% | ${float(r['post_CPI']):>7.2f} {float(r['post_ROI_pct']):>7.1f}% | {change:>+7.1f}pp | {r['campaign_name'][:40]}")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <csv_path>")
        sys.exit(1)
    csv_path = sys.argv[1]
    rows = load_data(csv_path)
    meaningful = [r for r in rows if float(r["pre_cost"]) > 0 and float(r["post_cost"]) > 0]
    print(f"总样本: {len(rows)} (有效: {len(meaningful)})")

    print_section("一、总体回测结论")
    report_overall(meaningful)

    print_section("二、按炸前 ROI 分层")
    report_roi_stratification(meaningful)

    print_section("三、按炸前用户规模分层")
    report_user_scale_stratification(meaningful)

    print_section("四、零回收分析 (炸后回收=$0)")
    report_zero_recovery(meaningful)

    print_section("五、典型案例 (ROI 变化极端)")
    report_top_cases(meaningful)

    print_section("六、控损规则设计 (盈利最大化, ROI=40% 盈亏线)")
    report_loss_control(meaningful)

    print()
    print("=" * 90)
    print("  报告结束")
    print("=" * 90)


if __name__ == "__main__":
    main()
