#!/usr/bin/env python3
"""
下载 FNSPID 新闻数据集 (HuggingFace)
- 1570万条新闻标题, S&P 500, 1999-2023
- 按 ticker 存成 parquet 文件
- 预计 13 分钟, ~500MB-1GB

用法:
    python3 run_download_fnspid.py              # 下载全部
    python3 run_download_fnspid.py --sp100      # 只下载 S&P 100 ticker
"""

import os
import sys
import json
import time
import argparse
import pandas as pd
from pathlib import Path

SP100_TICKERS = {
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA',
    'AVGO', 'ORCL', 'CRM', 'AMD', 'ADBE', 'INTC', 'CSCO', 'QCOM',
    'TXN', 'IBM', 'INTU', 'AMAT',
    'JPM', 'BAC', 'GS', 'MS', 'WFC', 'C', 'BLK', 'SCHW', 'AXP', 'BK',
    'USB', 'COF',
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'BMY', 'AMGN', 'GILD', 'MDT',
    'WMT', 'HD', 'PG', 'KO', 'PEP', 'COST', 'MCD', 'NKE', 'SBUX',
    'TGT', 'LOW',
    'CAT', 'BA', 'HON', 'GE', 'RTX', 'UPS', 'DE', 'LMT', 'MMM',
    'XOM', 'CVX', 'COP', 'SLB',
    'DIS', 'CMCSA', 'NFLX', 'T', 'VZ', 'TMUS',
    'NEE', 'DUK', 'SO',
    'V', 'MA', 'PYPL', 'ACN', 'LIN', 'UNP', 'PM',
}

CACHE_DIR = Path('./data/cache/news')


def main():
    parser = argparse.ArgumentParser(description='下载 FNSPID 新闻数据集')
    parser.add_argument('--sp100', action='store_true', help='只下载 S&P 100 ticker')
    parser.add_argument('--force', action='store_true', help='强制重新下载（覆盖缓存）')
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    index_file = CACHE_DIR / 'news_index.json'

    # 扫描已有的 parquet 缓存
    cached_tickers = set()
    cached_records = 0
    if not args.force:
        for f in CACHE_DIR.glob('*.parquet'):
            ticker = f.stem
            try:
                n = len(pd.read_parquet(f))
                if n > 0:
                    cached_tickers.add(ticker)
                    cached_records += n
            except Exception:
                pass
        if cached_tickers:
            print(f"已有缓存: {len(cached_tickers)} tickers, {cached_records:,} 条 (将跳过)")

    target_tickers = SP100_TICKERS if args.sp100 else None
    mode = "S&P 100" if args.sp100 else "全部 S&P 500"
    print(f"下载 FNSPID 新闻数据 ({mode})...")
    print(f"数据源: HuggingFace Zihan1004/FNSPID")
    print(f"预计: ~13 分钟 (全部) / ~3 分钟 (S&P 100)")
    print()

    from datasets import load_dataset

    hf_token = os.environ.get('HF_TOKEN')
    if not hf_token:
        print("警告: 未设置 HF_TOKEN, 可能会被限速 (429 错误)")
        print("请设置: export HF_TOKEN='hf_你的token'")
        print()

    # FNSPID
    print("[1/2] 下载 FNSPID...")
    ds = load_dataset('Zihan1004/FNSPID', split='train', streaming=True, token=hf_token)

    all_records = {}
    count = 0
    scanned = 0
    skipped = 0
    last_match_scan = 0  # 上次有新匹配时的扫描行数
    start = time.time()

    for row in ds:
        scanned += 1

        # 每 100 万行打印扫描进度
        if scanned % 1000000 == 0:
            elapsed = time.time() - start
            scan_speed = scanned / elapsed
            no_match_rows = scanned - last_match_scan
            print(f"  扫描 {scanned:>10,} 行 | 匹配 {count:,} 条 | {len(all_records)} tickers | "
                  f"{elapsed:.0f}s | {scan_speed:.0f} 行/秒")

            # 如果连续 500 万行没有新匹配，提前结束
            if count > 0 and no_match_rows > 5000000:
                print(f"  连续 {no_match_rows:,} 行无新匹配, 提前结束扫描")
                break

        symbol = row.get('Stock_symbol')
        if not symbol or not isinstance(symbol, str):
            skipped += 1
            continue

        ticker = symbol.strip().upper()
        if not ticker:
            skipped += 1
            continue

        if target_tickers and ticker not in target_tickers:
            continue

        if ticker in cached_tickers:
            continue

        headline = row.get('Article_title', '')
        date_str = row.get('Date', '')
        if not headline or not date_str:
            skipped += 1
            continue

        try:
            date = pd.Timestamp(date_str).tz_localize(None).normalize()
        except Exception:
            skipped += 1
            continue

        if ticker not in all_records:
            all_records[ticker] = []
        all_records[ticker].append({'date': date, 'headline': headline})
        count += 1
        last_match_scan = scanned

    elapsed = time.time() - start
    print(f"  FNSPID 完成: {count:,} 条, {len(all_records)} tickers, {elapsed:.0f}s")
    print(f"  跳过: {skipped:,} 条 (无效数据)")

    # ashraq/financial-news 补充
    print("\n[2/2] 下载 ashraq/financial-news (补充)...")
    try:
        ds2 = load_dataset('ashraq/financial-news', split='train', streaming=True, token=hf_token)
        count2 = 0
        for row in ds2:
            symbol = row.get('stock')
            if not symbol or not isinstance(symbol, str):
                continue
            ticker = symbol.strip().upper()
            if not ticker:
                continue
            if target_tickers and ticker not in target_tickers:
                continue

            if ticker in cached_tickers:
                continue

            headline = row.get('headline', '')
            date_str = row.get('date', '')
            if not headline or not date_str:
                continue

            try:
                date = pd.Timestamp(date_str).tz_localize(None).normalize()
            except Exception:
                try:
                    date = pd.Timestamp(date_str).normalize()
                except Exception:
                    continue

            if ticker not in all_records:
                all_records[ticker] = []
            all_records[ticker].append({'date': date, 'headline': headline})
            count2 += 1

        print(f"  ashraq 完成: {count2:,} 条")
    except Exception as e:
        print(f"  ashraq 失败 (跳过): {e}")

    # 保存新下载的
    print(f"\n保存到 {CACHE_DIR}/...")
    new_saved = 0
    for ticker, records in all_records.items():
        df = pd.DataFrame(records)
        df = df.drop_duplicates(subset=['date', 'headline'])
        df = df.sort_values('date').reset_index(drop=True)
        df.to_parquet(CACHE_DIR / f'{ticker}.parquet', index=False)
        new_saved += len(df)

    # 合并已缓存 + 新下载的 ticker 更新索引
    all_tickers = cached_tickers | set(all_records.keys())
    total_saved = cached_records + new_saved

    with open(index_file, 'w') as f:
        json.dump({
            'tickers': sorted(all_tickers),
            'total_records': total_saved,
            'source': 'FNSPID + ashraq/financial-news',
            'fetch_date': pd.Timestamp.now().isoformat(),
        }, f, indent=2)

    total_elapsed = time.time() - start

    print(f"\n{'='*50}")
    print(f"下载完成!")
    print(f"  新下载: {len(all_records)} tickers, {new_saved:,} 条")
    print(f"  已缓存: {len(cached_tickers)} tickers, {cached_records:,} 条")
    print(f"  总计: {len(all_tickers)} tickers, {total_saved:,} 条")
    print(f"  用时: {total_elapsed:.0f} 秒")
    print(f"  保存: {CACHE_DIR}/")
    print(f"{'='*50}")

    # 统计
    if all_records:
        sizes = [(t, len(r)) for t, r in all_records.items()]
        sizes.sort(key=lambda x: -x[1])
        print(f"\nTop 10 ticker:")
        for t, n in sizes[:10]:
            print(f"  {t:6s} {n:>8,} 条")

        all_dates = []
        for records in all_records.values():
            for r in records:
                all_dates.append(r['date'])
        if all_dates:
            print(f"\n日期范围: {min(all_dates).date()} ~ {max(all_dates).date()}")


if __name__ == '__main__':
    main()
