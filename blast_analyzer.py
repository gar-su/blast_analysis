#!/usr/bin/env python3
"""炸量广告分析脚本：从 SQL/CSV/Rule Log API 提取炸量记录，调用 ROI API 对比炸量前后指标。

Usage:
    python3 blast_analyzer.py <sql_file> [--output <csv_path>]
    python3 blast_analyzer.py --csv <csv_file> [--output <csv_path>]
    python3 blast_analyzer.py --rule-log --start <YYYY-MM-DD> --end <YYYY-MM-DD> [--rule-id <id>] [--output <csv_path>]

Example:
    python3 blast_analyzer.py np_rule_blast_log.sql
    python3 blast_analyzer.py np_rule_blast_log_0514.sql --output blast_0514.csv
    python3 blast_analyzer.py --csv blast_export.csv
    python3 blast_analyzer.py --rule-log --start 2026-05-27 --end 2026-05-30
"""

import re
import json
import csv
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Config
API_URL = "https://admin.netshort.com/prod-api/put/dashboard/hours/roi"
AUTH_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJsb2dpblR5cGUiOiJsb2dpbiIsImxvZ2luSWQiOiJzeXNfdXNlcjoyMDMwODk2MjUxNDc3Njg4MzIxIiwicm5TdHIiOiJmWUhpNWRINnoyQ1BQOFV5bUtWd1NPYlUzZ1hCSXNFUiIsInRlbmFudElkIjoiMDAwMDAwIiwidXNlcklkIjoyMDMwODk2MjUxNDc3Njg4MzIxfQ.1h51Xt1EeWyOxhwqYkLmEwq7wDboQq2HxVFHBV34BdA"
RULE_LOG_URL = (
    "https://admin.netshort.com/prod-api/rule/controlRuleLog/queryRunLogByPage"
)


def parse_blast_records(sql_path: str) -> list[dict]:
    """Extract is_blast=true records from SQL dump.

    Returns deduplicated list of dicts with keys:
        campaign_id, campaign_name, link_id, blast_time, blast_hour_seq
    """
    print(f"Reading {sql_path} ...")
    with open(sql_path, "r", encoding="utf-8") as f:
        content = f.read()

    data_start = content.find("BEGIN;")
    if data_start == -1:
        raise ValueError("No BEGIN; found in SQL file")

    data_section = content[data_start:]
    inserts = data_section.split("INSERT INTO ")
    print(f"  Total INSERTs: {len(inserts) - 1}")

    needle = "is_blast" + chr(92) + '":true'
    blast_records: dict[str, dict] = {}

    for ins in inserts[1:]:
        if needle not in ins:
            continue

        val_pos = ins.find("VALUES (")
        if val_pos == -1:
            continue
        val_content = ins[val_pos + 8 :]
        end_idx = val_content.find(");")
        if end_idx == -1:
            continue
        val_body = val_content[:end_idx]

        # Extract response_body JSON
        BS = chr(92)  # backslash
        blast_pos = val_body.find(needle)
        rb_start = val_body.rfind("'{" + BS + chr(34), 0, blast_pos)
        if rb_start == -1:
            continue
        rb_end = val_body.find(chr(125) + chr(39), blast_pos)
        if rb_end == -1:
            continue

        rb_str = val_body[rb_start + 1 : rb_end + 1]
        rb_clean = rb_str.replace(BS + chr(34), chr(34)).replace(BS + BS, BS)
        try:
            rb_json = json.loads(rb_clean)
        except json.JSONDecodeError:
            continue

        blast_time = rb_json.get("blast_time")
        blast_hour_seq = rb_json.get("blast_hour_seq")
        if blast_time is None:
            continue

        m = re.match(
            r"\s*(\d+),\s*(\d+),\s*'([^']*)',\s*'((?:[^'\\]|\\')*)',",
            val_body,
        )
        if not m:
            continue

        sql_campaign_id = m.group(3)
        campaign_name = m.group(4).replace(BS + chr(39), chr(39))
        link_id = campaign_name.split("-")[0] if campaign_name else ""

        if sql_campaign_id not in blast_records:
            blast_records[sql_campaign_id] = {
                "campaign_id": sql_campaign_id,
                "campaign_name": campaign_name,
                "link_id": link_id,
                "blast_time": blast_time,
                "blast_hour_seq": blast_hour_seq,
            }

    print(f"  Blast records (is_blast=true, with blast_time): {len(blast_records)}")
    return list(blast_records.values())


def fetch_hourly_roi(
    link_id: str, start_date: str, end_date: str, today: str
) -> list[dict]:
    """Call ROI dashboard API and return hourly data."""
    payload = json.dumps(
        {
            "appType": 1,
            "type": 1,
            "pageNum": 1,
            "pageSize": 400,
            "startDate": start_date,
            "endDate": end_date,
            "linkIds": [link_id],
            "channelNoFilterType": 1,
            "timeRange": [start_date, end_date],
            "today": today,
        }
    )

    cmd = [
        "curl",
        "-s",
        "--connect-timeout",
        "10",
        "--max-time",
        "60",
        API_URL,
        "-H",
        "accept: application/json",
        "-H",
        f"authorization: {AUTH_TOKEN}",
        "-H",
        "content-type: application/json;charset=UTF-8",
        "--data-raw",
        payload,
    ]

    resp = subprocess.check_output(cmd, timeout=90)
    data = json.loads(resp)
    return data.get("roiStatisticsVos", [])


def compute_metrics(hourly: list[dict], blast_time: datetime) -> tuple[dict, dict]:
    """Split hourly data at blast_time and compute pre/post aggregates."""
    pre = {"cost": 0.0, "recharge": 0.0, "users": 0, "pay": 0}
    post = {"cost": 0.0, "recharge": 0.0, "users": 0, "pay": 0}

    for h in hourly:
        hour_dt = datetime.strptime(h["hour"], "%Y-%m-%d %H:%M:%S")
        cost = float(h["cost"])
        recharge = float(h["rechargeAmount"])
        users = int(float(h["totalNormalUserCnt"]))
        pay = int(float(h.get("belongPayCnt", 0)))

        target = pre if hour_dt < blast_time else post
        target["cost"] += cost
        target["recharge"] += recharge
        target["users"] += users
        target["pay"] += pay

    return pre, post


def build_row(campaign: dict, pre: dict, post: dict) -> dict:
    """Build a single output row with computed metrics."""
    pre_cpi = pre["cost"] / pre["users"] if pre["users"] > 0 else 0
    post_cpi = post["cost"] / post["users"] if post["users"] > 0 else 0
    pre_roi = (pre["recharge"] / pre["cost"] * 100) if pre["cost"] > 0 else 0
    post_roi = (post["recharge"] / post["cost"] * 100) if post["cost"] > 0 else 0
    pre_pay_rate = (pre["pay"] / pre["users"] * 100) if pre["users"] > 0 else 0
    post_pay_rate = (post["pay"] / post["users"] * 100) if post["users"] > 0 else 0

    return {
        "campaign_id": campaign["campaign_id"],
        "campaign_name": campaign["campaign_name"],
        "link_id": campaign["link_id"],
        "blast_time": campaign["blast_time"],
        "blast_hour_seq": campaign["blast_hour_seq"],
        "pre_cost": round(pre["cost"], 2),
        "pre_rechargeAmount": round(pre["recharge"], 2),
        "pre_totalNormalUserCnt": pre["users"],
        "pre_belongPayCnt": pre["pay"],
        "pre_CPI": round(pre_cpi, 2),
        "pre_ROI_pct": round(pre_roi, 1),
        "pre_PayRate_pct": round(pre_pay_rate, 1),
        "post_cost": round(post["cost"], 2),
        "post_rechargeAmount": round(post["recharge"], 2),
        "post_totalNormalUserCnt": post["users"],
        "post_belongPayCnt": post["pay"],
        "post_CPI": round(post_cpi, 2),
        "post_ROI_pct": round(post_roi, 1),
        "post_PayRate_pct": round(post_pay_rate, 1),
    }


def write_csv(rows: list[dict], csv_path: str):
    """Write results to CSV."""
    fieldnames = list(rows[0].keys()) if rows else []
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows)} rows to {csv_path}")


def print_summary(rows: list[dict]):
    """Print terminal summary table."""
    print()
    print("=" * 155)
    print("SUMMARY")
    print("=" * 155)
    header = (
        f"{'campaign_id':>22s} | {'blast_time':>19s} | "
        f"{'pre_cost':>10s} {'pre_rev':>10s} {'pre_users':>9s} {'pre_CPI':>8s} {'pre_ROI':>8s} | "
        f"{'post_cost':>10s} {'post_rev':>10s} {'post_users':>9s} {'post_CPI':>8s} {'post_ROI':>8s}"
    )
    print(header)
    print("-" * len(header))

    t_pre = {"cost": 0.0, "recharge": 0.0, "users": 0}
    t_post = {"cost": 0.0, "recharge": 0.0, "users": 0}

    for r in sorted(rows, key=lambda x: x["blast_time"]):
        print(
            f"{r['campaign_id']:>22s} | {r['blast_time']:>19s} | "
            f"{r['pre_cost']:>10.2f} {r['pre_rechargeAmount']:>10.2f} {r['pre_totalNormalUserCnt']:>9d} "
            f"{r['pre_CPI']:>8.2f} {r['pre_ROI_pct']:>7.1f}% | "
            f"{r['post_cost']:>10.2f} {r['post_rechargeAmount']:>10.2f} {r['post_totalNormalUserCnt']:>9d} "
            f"{r['post_CPI']:>8.2f} {r['post_ROI_pct']:>7.1f}%"
        )
        t_pre["cost"] += r["pre_cost"]
        t_pre["recharge"] += r["pre_rechargeAmount"]
        t_pre["users"] += r["pre_totalNormalUserCnt"]
        t_post["cost"] += r["post_cost"]
        t_post["recharge"] += r["post_rechargeAmount"]
        t_post["users"] += r["post_totalNormalUserCnt"]

    pre_cpi = t_pre["cost"] / t_pre["users"] if t_pre["users"] > 0 else 0
    post_cpi = t_post["cost"] / t_post["users"] if t_post["users"] > 0 else 0
    pre_roi = (t_pre["recharge"] / t_pre["cost"] * 100) if t_pre["cost"] > 0 else 0
    post_roi = (t_post["recharge"] / t_post["cost"] * 100) if t_post["cost"] > 0 else 0

    print("-" * len(header))
    print(
        f"{'TOTAL':>22s} | {'':>19s} | "
        f"{t_pre['cost']:>10.2f} {t_pre['recharge']:>10.2f} {t_pre['users']:>9.0f} "
        f"{pre_cpi:>8.2f} {pre_roi:>7.1f}% | "
        f"{t_post['cost']:>10.2f} {t_post['recharge']:>10.2f} {t_post['users']:>9.0f} "
        f"{post_cpi:>8.2f} {post_roi:>7.1f}%"
    )

    print()
    print("CAMPAIGN LEGEND:")
    for r in sorted(rows, key=lambda x: x["blast_time"]):
        print(f"  {r['campaign_id']}: {r['campaign_name'][:120]}")


def parse_blast_from_csv(csv_path: str) -> list[dict]:
    """Extract is_blast=true records from CSV export.

    Returns deduplicated list of dicts with keys:
        campaign_id, campaign_name, link_id, blast_time, blast_hour_seq
    """
    print(f"Reading {csv_path} ...")
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    print(f"  Total rows: {len(all_rows)}")

    blast_records: dict[str, dict] = {}
    for row in all_rows:
        if row.get("is_blast") != "1":
            continue

        campaign_name = row.get("campaign_name", "")

        rb_str = row.get("response_body", "")
        if not rb_str:
            continue
        try:
            rb_json = json.loads(rb_str)
        except json.JSONDecodeError:
            continue

        campaign_id = rb_json.get("campaign_id", "")
        if not campaign_id:
            continue

        blast_time = rb_json.get("blast_time")
        blast_hour_seq = rb_json.get("blast_hour_seq")
        if blast_time is None:
            continue

        link_id = campaign_name.split("-")[0] if campaign_name else ""

        if campaign_id not in blast_records:
            blast_records[campaign_id] = {
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
                "link_id": link_id,
                "blast_time": blast_time,
                "blast_hour_seq": blast_hour_seq,
            }

    print(f"  Blast records (is_blast=1, with blast_time): {len(blast_records)}")
    return list(blast_records.values())


def fetch_blast_from_rule_log_api(
    start_date: str, end_date: str, rule_id: int = 3002
) -> list[dict]:
    """Page through rule log API and extract blast-trigger campaigns.

    Returns deduplicated list of dicts with keys:
        campaign_id, campaign_name, link_id, blast_time, blast_hour_seq
    """
    results: dict[str, dict] = {}
    page_num = 1
    page_size = 100

    while True:
        payload = json.dumps(
            {
                "adminUserId": None,
                "createTimeRange": [start_date, end_date],
                "pageNum": page_num,
                "pageSize": page_size,
                "ruleId": rule_id,
                "status": None,
                "deptId": None,
                "triggerOperate": None,
                "name": "",
                "advertiserId": None,
                "videoIds": [],
                "platformType": "1",
                "campaignId": None,
            }
        )
        cmd = [
            "curl",
            "-s",
            "--connect-timeout",
            "10",
            "--max-time",
            "60",
            RULE_LOG_URL,
            "-H",
            "accept: application/json",
            "-H",
            f"authorization: {AUTH_TOKEN}",
            "-H",
            "content-type: application/json;charset=UTF-8",
            "--data-raw",
            payload,
        ]
        resp = subprocess.check_output(cmd, timeout=90)
        data = json.loads(resp)
        rows = data.get("data", {}).get("rows", [])
        total = data.get("data", {}).get("total", 0)

        for row in rows:
            cname = row.get("cName", "")
            if not cname:
                continue
            campaign_id = cname.split("-", 1)[0] if "-" in cname else cname
            link_id = campaign_id
            created_time = row.get("createdTime", "")
            if not campaign_id or not created_time:
                continue

            blast_hour_seq = int(created_time[11:13]) if len(created_time) >= 13 else 0

            if campaign_id not in results:
                results[campaign_id] = {
                    "campaign_id": campaign_id,
                    "campaign_name": cname,
                    "link_id": link_id,
                    "blast_time": created_time,
                    "blast_hour_seq": blast_hour_seq,
                }

        fetched = page_num * page_size
        if fetched >= total:
            break
        page_num += 1

    print(f"  Rule log API: total={total}, unique campaigns={len(results)}")
    return list(results.values())



def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    use_csv = sys.argv[1] == "--csv"
    use_rule_log = sys.argv[1] == "--rule-log"
    data_path: str

    if use_csv:
        if len(sys.argv) < 3:
            print("ERROR: --csv requires a file path")
            sys.exit(1)
        data_path = sys.argv[2]
        opt_start = 3
    elif use_rule_log:
        data_path = ""
        opt_start = 2
    else:
        data_path = sys.argv[1]
        opt_start = 2

    start_date = "2026-05-04"
    end_date = "2026-05-14"
    rule_id = 3002
    output_path = None

    # Parse optional args
    args = sys.argv[opt_start:]
    i = 0
    while i < len(args):
        if args[i] == "--start" and i + 1 < len(args):
            start_date = args[i + 1]
            i += 2
        elif args[i] == "--end" and i + 1 < len(args):
            end_date = args[i + 1]
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        elif args[i] == "--rule-id" and i + 1 < len(args):
            rule_id = int(args[i + 1])
            i += 2
        else:
            i += 1

    if output_path is None:
        if use_rule_log:
            output_path = (
                f"rule_log_{rule_id}_{start_date}_{end_date}_blast_analysis.csv"
            )
        else:
            stem = Path(data_path).stem
            output_path = str(Path(data_path).parent / f"{stem}_blast_analysis.csv")

    # Step 1: Parse records
    if use_rule_log:
        campaigns = fetch_blast_from_rule_log_api(start_date, end_date, rule_id)
    elif use_csv:
        campaigns = parse_blast_from_csv(data_path)
    else:
        campaigns = parse_blast_records(data_path)
    if not campaigns:
        print("No blast records found.")
        return

    # Step 2: Process in chunks of 100, save each chunk to separate CSV
    CHUNK_SIZE = 100
    total = len(campaigns)
    total_chunks = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
    stem = Path(output_path).stem
    chunk_dir = Path(output_path).parent
    chunk_files = []
    all_rows = []

    print(
        f"\nFetching ROI data for {total} campaigns in {total_chunks} chunks of {CHUNK_SIZE} (sequential, no concurrency)..."
    )

    for chunk_num in range(total_chunks):
        start = chunk_num * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, total)
        chunk = campaigns[start:end]
        chunk_file = str(chunk_dir / f"{stem}_chunk_{chunk_num + 1:02d}.csv")
        offset = start

        print(
            f"\n--- Chunk {chunk_num + 1}/{total_chunks}: [{start + 1}-{end}] ({len(chunk)} campaigns) ---"
        )
        rows = []
        for i, camp in enumerate(chunk):
            cid = camp["campaign_id"]
            link_id = camp["link_id"]
            blast_time = datetime.strptime(camp["blast_time"], "%Y-%m-%d %H:%M:%S")

            try:
                camp_start = (blast_time - timedelta(days=2)).strftime("%Y-%m-%d")
                camp_end = (blast_time + timedelta(days=2)).strftime("%Y-%m-%d")
                hourly = fetch_hourly_roi(link_id, camp_start, camp_end, camp_end)
            except Exception as e:
                print(f"  [{offset + i + 1}/{total}] {cid} API ERROR: {e}")
                continue

            pre, post = compute_metrics(hourly, blast_time)
            row = build_row(camp, pre, post)
            rows.append(row)

            pre_roi = f"{row['pre_ROI_pct']:.1f}%"
            post_roi = f"{row['post_ROI_pct']:.1f}%"
            print(
                f"  [{offset + i + 1}/{total}] {cid} "
                f"blast={camp['blast_time']} | "
                f"pre: ${row['pre_cost']:.2f} rev=${row['pre_rechargeAmount']:.2f} u={row['pre_totalNormalUserCnt']} CPI={row['pre_CPI']:.2f} ROI={pre_roi} | "
                f"post: ${row['post_cost']:.2f} rev=${row['post_rechargeAmount']:.2f} u={row['post_totalNormalUserCnt']} CPI={row['post_CPI']:.2f} ROI={post_roi}"
            )
            time.sleep(0.3)

        write_csv(rows, chunk_file)
        chunk_files.append(chunk_file)
        all_rows.extend(rows)
        print(
            f"  Chunk {chunk_num + 1} done: {len(rows)} results saved to {Path(chunk_file).name}"
        )

    if not all_rows:
        print("No results to output.")
        return

    # Step 3: Merge chunk CSVs into final output
    write_csv(all_rows, output_path)
    print(f"\nMerged {len(all_rows)} rows into {output_path}")

    # Step 4: Print summary
    print_summary(all_rows)


if __name__ == "__main__":
    main()
