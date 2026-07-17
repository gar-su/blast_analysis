#!/usr/bin/env python3
"""Check rule 3077's last 10 ads against the ML blast detector model.

For each ad: fetch hourly data before blast_time, feed to model, compare.
"""
import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# --- Config ---
API_URL = "https://admin.netshort.com/prod-api/put/dashboard/hours/roi"
AUTH_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJsb2dpblR5cGUiOiJsb2dpbiIsImxvZ2luSWQiOiJzeXNfdXNlcjoyMDMwODk2MjUxNDc3Njg4MzIxIiwicm5TdHIiOiJ0ZkxrQThWQUlmT3pJMGE5UVBycTVwSGRoMnZUWFpEcSIsInRlbmFudElkIjoiMDAwMDAwIiwidXNlcklkIjoyMDMwODk2MjUxNDc3Njg4MzIxfQ.aWJWjYdcrWJqYN5DdaUmbkN2-GOoxJ6VQDvGCxR0heI"

CSV_PATH = "/Users/gar/blast_analysis/rule_log_3077_2026-06-01_2026-06-05_blast_analysis.csv"

# Add detector to path
sys.path.insert(0, "/Users/gar/ad_blast_detector")
from ad_state_model.predictor import AdStatePredictor


def fetch_hourly_roi(link_id: str, start_date: str, end_date: str, today: str) -> list[dict]:
    payload = json.dumps({
        "appType": 1, "type": 1, "pageNum": 1, "pageSize": 400,
        "startDate": start_date, "endDate": end_date,
        "linkIds": [link_id], "channelNoFilterType": 1,
        "timeRange": [start_date, end_date], "today": today,
    })
    cmd = [
        "curl", "-s", "--connect-timeout", "10", "--max-time", "60",
        API_URL,
        "-H", "accept: application/json",
        "-H", f"authorization: {AUTH_TOKEN}",
        "-H", "content-type: application/json;charset=UTF-8",
        "--data-raw", payload,
    ]
    resp = subprocess.check_output(cmd, timeout=90)
    data = json.loads(resp)
    return data.get("roiStatisticsVos", [])


def main():
    # Load predictor
    print("Loading blast detector model...")
    predictor = AdStatePredictor()
    print("Model loaded.\n")

    # Read last 10 ads from CSV
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    # Sort by blast_time desc, take last 10
    rows.sort(key=lambda r: r["blast_time"], reverse=True)
    last_10 = rows[:10]

    print(f"{'=' * 120}")
    print(f"Checking last {len(last_10)} ads from rule 3077 against ML model")
    print(f"{'=' * 120}\n")

    results = []
    for i, ad in enumerate(last_10):
        campaign_id = ad["campaign_id"]
        campaign_name = ad["campaign_name"]
        link_id = ad["link_id"]
        blast_time_str = ad["blast_time"]
        blast_time = datetime.strptime(blast_time_str, "%Y-%m-%d %H:%M:%S")
        pre_cost = float(ad["pre_cost"])
        pre_roi = float(ad["pre_ROI_pct"]) / 100

        # Fetch 2 days before blast
        start_date = (blast_time - timedelta(days=2)).strftime("%Y-%m-%d")
        end_date = blast_time.strftime("%Y-%m-%d")
        today = blast_time.strftime("%Y-%m-%d")

        print(f"[{i+1}/10] {campaign_id} | {campaign_name[:60]}")
        print(f"  link_id={link_id}, blast_time={blast_time_str}")

        try:
            hourly = fetch_hourly_roi(link_id, start_date, end_date, today)
        except Exception as e:
            print(f"  ERROR fetching ROI data: {e}")
            results.append({"campaign_id": campaign_id, "is_blast": "API_ERROR", "error": str(e)})
            continue

        # Filter to pre-blast hours only, sort by time
        pre_hours = []
        for h in hourly:
            hour_dt = datetime.strptime(h["hour"], "%Y-%m-%d %H:%M:%S")
            if hour_dt < blast_time:
                pre_hours.append(h)
        pre_hours.sort(key=lambda h: h["hour"])

        print(f"  Pre-blast hours: {len(pre_hours)}")

        if len(pre_hours) < 7:
            print(f"  SKIP: insufficient history ({len(pre_hours)} < 7)")
            results.append({
                "campaign_id": campaign_id, "is_blast": False,
                "error": f"insufficient history: {len(pre_hours)}",
            })
            continue

        # Convert to model input format
        history = []
        for h in pre_hours:
            history.append({
                "hour": h["hour"],
                "cost_h": float(h["cost"]),
                "show_cnt": 0.0,  # API doesn't return this
                "click_cnt": 0.0,
                "belong_h_cnt": float(h["totalNormalUserCnt"]),
                "belong_pay_cnt": float(h.get("belongPayCnt", 0)),
                "vip_pay_cnt": 0.0,
                "d0_order_amt": float(h["rechargeAmount"]),
                "business_type": 1,
                "link_language": "unknown",
            })

        # Predict
        try:
            result = predictor.predict_single(campaign_id, history)
        except Exception as e:
            print(f"  ERROR during prediction: {e}")
            results.append({"campaign_id": campaign_id, "is_blast": "PREDICT_ERROR", "error": str(e)})
            continue

        model_is_blast = result.get("is_blast", False)
        model_blast_time = result.get("blast_time", None)
        model_blast_seq = result.get("blast_hour_seq", None)
        details = result.get("details", {})

        # Determine agreement
        actual_hour = blast_time.strftime("%Y-%m-%d %H:00:00")
        model_hour = model_blast_time[:13] + ":00:00" if model_blast_time else None

        if model_is_blast and model_hour == actual_hour:
            match = "MATCH (time exact)"
        elif model_is_blast:
            # Check if model blast is within 2 hours
            model_dt = datetime.strptime(model_blast_time, "%Y-%m-%d %H:%M:%S")
            diff_h = abs((model_dt - blast_time).total_seconds()) / 3600
            match = f"MATCH (offset {diff_h:.0f}h)" if diff_h <= 2 else f"MISMATCH (model: {model_blast_time})"
        elif model_is_blast:
            match = f"MISMATCH (model says blast at {model_blast_time})"
        else:
            match = "MISS (model says NO blast)"

        # Summary of surge/anomaly details
        surge_count = sum(1 for d in (details or {}).values() if isinstance(d, dict) and d.get("surge_signal"))
        anomaly_count = sum(1 for d in (details or {}).values() if isinstance(d, dict) and d.get("model_anomaly"))

        print(f"  Rule engine says: BLAST at {blast_time_str}")
        print(f"  Model says:       {'BLAST' if model_is_blast else 'NO BLAST'} at {model_blast_time}")
        print(f"  Verdict:          {match}")
        print(f"  Pre-cost=${pre_cost:.2f}, pre-ROI={pre_roi:.1%}, surge_points={surge_count}, anomaly_points={anomaly_count}")

        # Print last 3 detail points for debugging
        if details:
            detail_keys = sorted(details.keys(), key=lambda k: details[k].get("hour", ""))[-3:]
            for k in detail_keys:
                d = details[k]
                print(f"    {d.get('hour','?')} | cost={d.get('current_cost','?')} upper={d.get('cost_upper_bound','?')} "
                      f"surge={d.get('surge_signal','?')} anomaly={d.get('model_anomaly','?')} "
                      f"score={d.get('anomaly_score','?')} thr={d.get('threshold_used','?')}")

        results.append({
            "campaign_id": campaign_id,
            "campaign_name": campaign_name[:60],
            "link_id": link_id,
            "blast_time": blast_time_str,
            "model_is_blast": model_is_blast,
            "model_blast_time": model_blast_time,
            "verdict": match,
            "pre_cost": pre_cost,
            "pre_roi": pre_roi,
        })
        print()

    # Summary
    print(f"{'=' * 120}")
    print("SUMMARY")
    print(f"{'=' * 120}")
    matches = sum(1 for r in results if "MATCH" in str(r.get("verdict", "")))
    misses = sum(1 for r in results if "MISS" in str(r.get("verdict", "")))
    mismatches = sum(1 for r in results if "MISMATCH" in str(r.get("verdict", "")))
    errors = sum(1 for r in results if "ERROR" in str(r.get("verdict", "")))
    print(f"  Total: {len(results)} | Match: {matches} | Miss: {misses} | Mismatch: {mismatches} | Error: {errors}")
    print(f"  Match rate: {matches}/{len(results)-errors} = {matches/(len(results)-errors)*100:.0f}%" if (len(results)-errors) > 0 else "  N/A")
    print()

    for r in results:
        print(f"  {r['campaign_id']} | {r['blast_time']} | model={'BLAST' if r['model_is_blast'] else 'NO'} | {r['verdict']}")


if __name__ == "__main__":
    main()
