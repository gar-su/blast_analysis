# 炸量广告回测分析项目

## 项目概述

两阶段流水线：**数据采集** → **回测报告**

- `blast_analyzer.py` — 从 Rule Log API / SQL dump / CSV 提取炸量记录，调用 ROI API 拉取小时级数据，计算炸前炸后指标，输出 CSV
- `blast_backtest_report.py` — 读取 CSV，打印分层回测报告（ROI 分层、消耗分层、零回收、控损规则）
- `signal_backtest.py` — 基于小时级 CSV 回测信号规则（充值次数/集中度/尾段零回收三个信号），评估跳过不安全广告后的盈利改善
- `check_model_vs_rule.py` — 对比 ML 炸量检测模型与规则引擎的判断差异（需 `/Users/gar/ad_blast_detector` 依赖）
- `fetch_hourly_for_rules.py` — 为指定规则 CSV 批量拉取 ±3 天小时级 ROI 数据，输出 `hourly_raw_{rule_id}.csv`

## 常用命令

### 1. 采集数据（主要方式：Rule Log API）

```bash
python3 blast_analyzer.py --rule-log --start 2026-05-26 --end 2026-06-01 --rule-id 3002
```

产出：`rule_log_3002_<start>_<end>_blast_analysis_chunk_*.csv`（中间文件）+ 合并后的 `..._blast_analysis.csv`

### 2. 采集数据（备用：SQL dump / CSV）

```bash
python3 blast_analyzer.py np_rule_blast_log.sql --today 2026-05-14
python3 blast_analyzer.py --csv blast_export.csv --today 2026-05-18
```

### 3. 生成回测报告

```bash
python3 blast_backtest_report.py <csv_path>
```

## 关键依赖

- **纯标准库**，无 pip 依赖
- **系统依赖**: `curl` 必须在 PATH 上
- **网络**: 必须能访问 `admin.netshort.com`（需内网/VPN），Bearer Token 硬编码在 `blast_analyzer.py:29`
- Python 3.13+

## API 说明

| API | URL | 用途 |
|-----|-----|------|
| ROI 小时数据 | `admin.netshort.com/prod-api/put/dashboard/hours/roi` | 按 link_id + 时间窗口拉 cost/recharge/users/pay 等指标 |
| Rule Log 分页 | `admin.netshort.com/prod-api/rule/controlRuleLog/queryRunLogByPage` | 按 rule_id + 日期范围拉取触发了炸量规则的 campaign 列表 |

调用方式：`subprocess.check_output(["curl", "-s", ...], timeout=30)`

## 数据结构

### 采集输出 CSV 列（19 列）

```
campaign_id, campaign_name, link_id, blast_time, blast_hour_seq,
pre_cost, pre_rechargeAmount, pre_totalNormalUserCnt, pre_belongPayCnt, pre_CPI, pre_ROI_pct, pre_PayRate_pct,
post_cost, post_rechargeAmount, post_totalNormalUserCnt, post_belongPayCnt, post_CPI, post_ROI_pct, post_PayRate_pct
```

CPI = cost/users, ROI% = recharge/cost * 100, PayRate% = pay_users/users * 100

### Rule Log API 响应结构

```json
{"data": {"total": N, "records": [{"campaignId": ..., "campaignName": ..., "linkId": ..., "createTime": ..., "responseBody": "包含 is_blast、blastHourSeq 等"}]}}
```

## 设计要点

- **API 限流**: blast_analyzer.py 每次 API 调用后 `time.sleep(0.3)`，分块处理（CHUNK_SIZE=100），每块输出独立 CSV 后合并，防止全量失败
- **盈亏平衡线**: 全项目统一使用 **ROI = 40%** 作为盈亏线，盈利定义为 `recharge - 0.4 * cost`
- **炸前窗口**: blast_analyzer.py 取 blast_time **±2 天** 的 ROI 数据；signal_backtest.py 用 **前 24 小时** 做信号检测；fetch_hourly_for_rules.py 取 **±3 天**
- **AUTH_TOKEN**: 硬编码在 `blast_analyzer.py:27`、`check_model_vs_rule.py:15`、`fetch_hourly_for_rules.py:12` 三处，Token 过期时需同步更新
- **Rule Log API 的分页**: pageSize=100，逐页拉取直到 `fetched >= total`
- **marker 文件**: `blast_backtest_report.md` 和 `blast_multi_report.md` 是历史分析结论的存档，非自动生成

