#!/usr/bin/env python3
"""Sequentially fetch hourly ROI data for campaigns in 3077 and 3002 CSVs."""

import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta

API_URL = "https://admin.netshort.com/prod-api/put/dashboard/hours/roi"
AUTH_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJsb2dpblR5cGUiOiJsb2dpbiIsImxvZ2luSWQiOiJzeXNfdXNlcjoyMDMwODk2MjUxNDc3Njg4MzIxIiwicm5TdHIiOiJmWUhpNWRINnoyQ1BQOFV5bUtWd1NPYlUzZ1hCSXNFUiIsInRlbmFudElkIjoiMDAwMDAwIiwidXNlcklkIjoyMDMwODk2MjUxNDc3Njg4MzIxfQ.1h51Xt1EeWyOxhwqYkLmEwq7wDboQq2HxVFHBV34BdA"


def fetch_hourly_roi(link_id: str, start_date: str, end_date: str) -> list[dict]:
    payload = json.dumps({
        "appType": 1, "type": 1, "pageNum": 1, "pageSize": 400,
        "startDate": start_date, "endDate": end_date,
        "linkIds": [link_id], "channelNoFilterType": 1,
        "timeRange": [start_date, end_date], "today": end_date,
    })
    cmd = [
        "curl", "-s", "--connect-timeout", "10", "--max-time", "60",
        API_URL, "-H", "accept: application/json",
        "-H", f"authorization: {AUTH_TOKEN}",
        "-H", "content-type: application/json;charset=UTF-8",
        "--data-raw", payload,
    ]
    try:
        resp = subprocess.check_output(cmd, timeout=90)
        data = json.loads(resp)
        return data.get("roiStatisticsVos", [])
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


def parse_campaign_name(cname: str) -> tuple[str, str, str]:
    """Extract video_name, rule_name, ad_user from campaign name.
    Campaign name format: {id}-{shortcode}-FB-{date}-{video}-{region}-w2a-{ad_user}-{suffix}
    Rule name is not in the campaign name for 3077/3002 — we'll use the rule_id."""
    parts = cname.split("-")
    # video_name is typically at index 4 (after LA037-FB-0607)
    video_name = ""
    ad_user = ""
    for i, p in enumerate(parts):
        if p == "FB" and i + 3 < len(parts):
            video_name = parts[i + 3]
        if p == "w2a" and i + 1 < len(parts):
            ad_user = parts[i + 1]
    return video_name, "", ad_user


def main():
    csv_files = [
        ("/Users/gar/blast_analysis/rule_log_3077_2026-06-02_2026-06-08_blast_analysis.csv", "3077"),
        ("/Users/gar/blast_analysis/rule_log_3002_2026-06-02_2026-06-08_blast_analysis.csv", "3002"),
    ]

    for csv_path, rule_id in csv_files:
        out_path = f"/Users/gar/blast_analysis/hourly_raw_{rule_id}.csv"
        print(f"\n{'='*60}")
        print(f"Processing rule {rule_id}: {csv_path}")
        print(f"Output: {out_path}")
        print(f"{'='*60}")

        campaigns = []
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                campaigns.append(row)

        n = len(campaigns)
        print(f"Total campaigns: {n}")

        with open(out_path, "w", newline="", encoding="utf-8") as out:
            writer = csv.writer(out)
            writer.writerow([
                "link_id", "cname", "blast_time", "video_name", "rule_name", "ad_user",
                "hour", "hours_from_blast",
                "cost", "rechargeAmount", "totalNormalUserCnt", "belongPayCnt",
                "roi", "cpi", "payRate",
            ])

            for i, row in enumerate(campaigns):
                link_id = row["link_id"]
                blast_time_str = row["blast_time"]
                blast_dt = datetime.strptime(blast_time_str, "%Y-%m-%d %H:%M:%S")
                cname = row["campaign_name"]
                video_name, _, ad_user = parse_campaign_name(cname)

                # 3 days before to 3 days after
                start_date = (blast_dt - timedelta(days=3)).strftime("%Y-%m-%d")
                end_date = (blast_dt + timedelta(days=3)).strftime("%Y-%m-%d")

                print(f"  [{i+1}/{n}] {link_id} | {blast_time_str} | {start_date} -> {end_date}", end="", flush=True)

                hourly = fetch_hourly_roi(link_id, start_date, end_date)
                row_count = 0
                for h in hourly:
                    hour_str = h.get("hour", "")
                    try:
                        hour_dt = datetime.strptime(hour_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        hour_dt = datetime.strptime(hour_str, "%Y-%m-%d")
                    hours_from_blast = round((hour_dt - blast_dt).total_seconds() / 3600, 1)
                    cost = float(h.get("cost", 0))
                    recharge = float(h.get("rechargeAmount", 0))
                    users = int(float(h.get("totalNormalUserCnt", 0)))
                    pay = int(float(h.get("belongPayCnt", 0)))
                    roi = round(recharge / cost * 100, 2) if cost > 0 else 0
                    cpi = round(cost / users, 2) if users > 0 else 0
                    pay_rate = round(pay / users * 100, 2) if users > 0 else 0
                    writer.writerow([
                        link_id, cname, blast_time_str, video_name, rule_id, ad_user,
                        hour_str, hours_from_blast,
                        cost, recharge, users, pay,
                        roi, cpi, pay_rate,
                    ])
                    row_count += 1

                print(f" -> {row_count} hours")
                time.sleep(0.3)

        print(f"\nDone: {out_path}")


if __name__ == "__main__":
    main()
