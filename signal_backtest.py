#!/usr/bin/env python3
"""Backtest signal-based blast rules on hourly data.

Rule: only blast if the campaign passes a safety check in the 24h before blast:
  Crash signals (any one = skip blast):
    (1) recharge count < 4
    (2) max single recharge / total pre recharge >= 50%
    (3) last 6 hours $0 recharge AND cost > 0

Profit = recharge - 0.4 * cost  (breakeven at 40% ROI)
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta

HOURS_PRE = 24


def analyze_rule(filepath: str, label: str):
    print(f"\n{'='*80}")
    print(f"  {label}: {filepath}")
    print(f"{'='*80}")

    # Group hourly data by link_id
    campaigns: dict[str, list[dict]] = defaultdict(list)
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            campaigns[row["link_id"]].append(row)

    results = []
    for link_id, rows in campaigns.items():
        blast_time = datetime.strptime(rows[0]["blast_time"], "%Y-%m-%d %H:%M:%S")
        pre_start = blast_time - timedelta(hours=HOURS_PRE)

        # Pre-blast stats
        pre_rech_total = 0.0
        pre_cost_total = 0.0
        pre_rech_count = 0
        pre_max_rech = 0.0
        # Last 6 hours
        last6_rech = 0.0
        last6_cost = 0.0

        for r in rows:
            hour = datetime.strptime(r["hour"], "%Y-%m-%d %H:%M:%S")
            cost = float(r["cost"])
            rech = float(r["rechargeAmount"])

            if pre_start <= hour < blast_time:
                pre_rech_total += rech
                pre_cost_total += cost
                if rech > 0:
                    pre_rech_count += 1
                    pre_max_rech = max(pre_max_rech, rech)
                # Last 6 hours before blast
                if hour >= blast_time - timedelta(hours=6):
                    last6_rech += rech
                    last6_cost += cost
            elif hour >= blast_time:
                # Post-blast
                pass

        # Signals
        signal1 = pre_rech_count < 4
        signal2 = (pre_max_rech / pre_rech_total >= 0.5) if pre_rech_total > 0 else False
        signal3 = (last6_rech == 0 and last6_cost > 0)
        unsafe = signal1 or signal2 or signal3

        # Post-blast profit (all post hours)
        post_cost = 0.0
        post_rech = 0.0
        for r in rows:
            hour = datetime.strptime(r["hour"], "%Y-%m-%d %H:%M:%S")
            if hour >= blast_time:
                post_cost += float(r["cost"])
                post_rech += float(r["rechargeAmount"])

        profit = post_rech - 0.4 * post_cost
        results.append({
            "link_id": link_id,
            "blast_time": blast_time,
            "pre_cost": pre_cost_total,
            "pre_rech": pre_rech_total,
            "pre_rech_count": pre_rech_count,
            "pre_max_rech": pre_max_rech,
            "conc_pct": round(pre_max_rech / pre_rech_total * 100, 1) if pre_rech_total > 0 else 0,
            "last6_rech": last6_rech,
            "last6_cost": last6_cost,
            "signal1": signal1,
            "signal2": signal2,
            "signal3": signal3,
            "unsafe": unsafe,
            "post_cost": post_cost,
            "post_rech": post_rech,
            "profit": profit,
        })

    n = len(results)
    n_unsafe = sum(1 for r in results if r["unsafe"])
    n_safe = n - n_unsafe

    # All campaigns
    all_cost = sum(r["post_cost"] for r in results)
    all_rech = sum(r["post_rech"] for r in results)
    all_profit = sum(r["profit"] for r in results)

    # Safe-only (if we skip unsafe)
    safe_results = [r for r in results if not r["unsafe"]]
    safe_cost = sum(r["post_cost"] for r in safe_results)
    safe_rech = sum(r["post_rech"] for r in safe_results)
    safe_profit = sum(r["profit"] for r in safe_results)
    safe_roi = round(safe_rech / safe_cost * 100, 1) if safe_cost > 0 else 0

    # Unsafe (skipped — would have saved cost)
    unsafe_results = [r for r in results if r["unsafe"]]
    unsafe_cost = sum(r["post_cost"] for r in unsafe_results)
    unsafe_rech = sum(r["post_rech"] for r in unsafe_results)
    unsafe_profit = sum(r["profit"] for r in unsafe_results)
    unsafe_roi = round(unsafe_rech / unsafe_cost * 100, 1) if unsafe_cost > 0 else 0

    print(f"\n  Total campaigns: {n}")
    print(f"  Unsafe (would skip): {n_unsafe} ({n_unsafe/n*100:.1f}%)")
    print(f"  Safe (would blast):   {n_safe} ({n_safe/n*100:.1f}%)")

    print(f"\n  {'':>20} {'Campaigns':>10} {'Cost':>10} {'Recharge':>10} {'Profit':>10} {'ROI':>8}")
    print(f"  {'─'*70}")
    print(f"  {'All (blast all)':>20} {n:>10} {all_cost:>10.0f} {all_rech:>10.0f} {all_profit:>+10.0f} {round(all_rech/all_cost*100,1) if all_cost>0 else 0:>7.1f}%")
    print(f"  {'Rule: skip unsafe':>20} {n_safe:>10} {safe_cost:>10.0f} {safe_rech:>10.0f} {safe_profit:>+10.0f} {safe_roi:>7.1f}%")
    print(f"  {'Skipped (saved):':>20} {n_unsafe:>10} {unsafe_cost:>10.0f} {unsafe_rech:>10.0f} {unsafe_profit:>+10.0f} {unsafe_roi:>7.1f}%")

    improvement = safe_profit - all_profit
    if all_profit != 0:
        pct_improve = improvement / abs(all_profit) * 100
        print(f"\n  Improvement: {improvement:+.0f} ({pct_improve:+.1f}%)")

    # Signal breakdown
    print(f"\n  Signal breakdown:")
    s1 = sum(1 for r in results if r["signal1"])
    s2 = sum(1 for r in results if r["signal2"])
    s3 = sum(1 for r in results if r["signal3"])
    print(f"    (1) rech_count < 4:          {s1} campaigns")
    print(f"    (2) max_rech/total >= 50%:   {s2} campaigns")
    print(f"    (3) last6h $0 rech + spend:  {s3} campaigns")

    # ROI buckets for safe campaigns
    print(f"\n  Safe campaign ROI distribution:")
    buckets = [("0-20%", 0, 20), ("20-40%", 20, 40), ("40-60%", 40, 60),
               ("60-100%", 60, 100), ("100%+", 100, 9999)]
    safe_with_roi = [(r, r["post_rech"]/r["post_cost"]*100) for r in safe_results if r["post_cost"] > 0]
    for label, lo, hi in buckets:
        in_range = [(r, roi) for r, roi in safe_with_roi if lo <= roi < hi]
        profit = sum(r["profit"] for r, _ in in_range)
        print(f"    {label:>12}: {len(in_range):>3} campaigns  profit={profit:+.0f}")

    return results


if __name__ == "__main__":
    results_3077 = analyze_rule("/Users/gar/blast_analysis/hourly_raw_3077.csv", "Rule 3077")
    results_3002 = analyze_rule("/Users/gar/blast_analysis/hourly_raw_3002.csv", "Rule 3002")

    print(f"\n{'='*80}")
    print(f"  COMBINED (3077 + 3002)")
    print(f"{'='*80}")
    all_r = results_3077 + results_3002
    n = len(all_r)
    all_cost = sum(r["post_cost"] for r in all_r)
    all_rech = sum(r["post_rech"] for r in all_r)
    all_profit = sum(r["profit"] for r in all_r)
    safe_r = [r for r in all_r if not r["unsafe"]]
    safe_cost = sum(r["post_cost"] for r in safe_r)
    safe_rech = sum(r["post_rech"] for r in safe_r)
    safe_profit = sum(r["profit"] for r in safe_r)
    unsafe_r = [r for r in all_r if r["unsafe"]]
    unsafe_profit = sum(r["profit"] for r in unsafe_r)
    unsafe_cost = sum(r["post_cost"] for r in unsafe_r)
    print(f"  All:    {n} campaigns, profit={all_profit:+.0f}, roi={round(all_rech/all_cost*100,1) if all_cost>0 else 0}%")
    print(f"  Safe:   {len(safe_r)} campaigns, profit={safe_profit:+.0f}, roi={round(safe_rech/safe_cost*100,1) if safe_cost>0 else 0}%")
    print(f"  Unsafe: {len(unsafe_r)} campaigns, profit={unsafe_profit:+.0f} (skipped, cost saved={unsafe_cost:.0f})")
    print(f"  Improvement: {safe_profit - all_profit:+.0f}")
