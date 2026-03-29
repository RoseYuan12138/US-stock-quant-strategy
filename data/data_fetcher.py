"""
美股数据获取模块
使用 yfinance 获取历史 OHLCV 数据，支持批量下载和本地缓存
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import yfinance as yf

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DataFetcher:
    """美股数据获取器"""
    
    def __init__(self, cache_dir="./data/cache"):
        """
        初始化数据获取器
        
        Args:
            cache_dir: 数据缓存目录
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.cache_dir / "metadata.json"
        self.metadata = self._load_metadata()
    
    def _load_metadata(self):
        """加载元数据（记录最后更新时间）"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_metadata(self):
        """保存元数据"""
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)
    
    def _get_cache_file(self, ticker):
        """获取缓存文件路径"""
        return self.cache_dir / f"{ticker.upper()}.csv"
    
    def fetch_historical_data(self, ticker, start_date=None, end_date=None, 
                             use_cache=True, force_update=False):
        """
        获取历史数据
        
        Args:
            ticker: 股票代码 (e.g., 'AAPL')
            start_date: 开始日期 (e.g., '2024-01-01')
            end_date: 结束日期 (default: today)
            use_cache: 是否使用缓存
            force_update: 是否强制更新（忽略缓存）
        
        Returns:
            pd.DataFrame: 包含 Open, High, Low, Close, Volume 的数据框
        """
        ticker = ticker.upper()
        
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        if start_date is None:
            # 默认获取最近 2 年
            start_date = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
        
        # 尝试从缓存加载
        if use_cache and not force_update:
            cached_data = self._load_from_cache(ticker)
            if cached_data is not None and len(cached_data) > 50:  # 必须有足够的历史数据
                # 检查缓存是否需要更新（是否包含今天的数据）
                last_cached_date = cached_data.index[-1].strftime('%Y-%m-%d')
                today = datetime.now().strftime('%Y-%m-%d')
                
                if last_cached_date == today:
                    logger.info(f"{ticker}: 使用缓存数据 (最后更新: {last_cached_date})")
                    return cached_data
                else:
                    # 缓存数据足够，直接返回
                    logger.info(f"{ticker}: 使用缓存数据，最后更新 {last_cached_date}")
                    return cached_data
        
        # 从 yfinance 获取数据
        try:
            logger.info(f"{ticker}: 从 {start_date} 到 {end_date} 下载数据...")
            raw_data = yf.download(ticker, start=start_date, end=end_date, 
                              progress=False, interval='1d')
            
            if raw_data is None or len(raw_data) == 0:
                logger.warning(f"{ticker}: 未获取到数据")
                return None
            
            # 处理多重索引列（yfinance 返回的格式）
            if isinstance(raw_data.columns, pd.MultiIndex):
                # 删除 ticker 级别，只保留指标级别
                raw_data.columns = raw_data.columns.droplevel(1)
            
            # 删除 NaN 行
            raw_data = raw_data.dropna()
            
            if len(raw_data) == 0:
                logger.warning(f"{ticker}: 清理后无有效数据")
                return None
            
            # 只保留需要的列
            cols_to_keep = ['Open', 'High', 'Low', 'Close', 'Volume']
            available_cols = [c for c in cols_to_keep if c in raw_data.columns]
            
            if not available_cols:
                logger.error(f"{ticker}: 未找到必要列。可用列: {list(raw_data.columns)}")
                return None
            
            data = raw_data[available_cols].copy()
            
            logger.info(f"{ticker}: 成功获取 {len(data)} 行数据")
            
            # 保存到缓存
            if use_cache:
                self._save_to_cache(ticker, data)
            
            return data
        
        except Exception as e:
            logger.error(f"{ticker}: 数据获取失败 - {str(e)}")
            return None
    
    def fetch_batch(self, tickers, start_date=None, end_date=None):
        """
        批量获取多只股票数据
        
        Args:
            tickers: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            dict: {ticker: DataFrame}
        """
        results = {}
        for ticker in tickers:
            data = self.fetch_historical_data(ticker, start_date, end_date)
            if data is not None:
                results[ticker] = data
        
        return results
    
    def _save_to_cache(self, ticker, data):
        """保存数据到缓存"""
        cache_file = self._get_cache_file(ticker)
        try:
            data.to_csv(cache_file)
            self.metadata[ticker] = datetime.now().isoformat()
            self._save_metadata()
            logger.info(f"{ticker}: 数据已缓存到 {cache_file}")
        except Exception as e:
            logger.error(f"{ticker}: 缓存保存失败 - {str(e)}")
    
    def _load_from_cache(self, ticker):
        """从缓存加载数据"""
        cache_file = self._get_cache_file(ticker)
        if not cache_file.exists():
            return None
        
        try:
            data = pd.read_csv(cache_file, index_col=0, parse_dates=True, infer_datetime_format=True)
            # 确保索引是 DatetimeIndex
            data.index = pd.to_datetime(data.index)
            logger.info(f"{ticker}: 从缓存加载 {len(data)} 行数据")
            return data
        except Exception as e:
            logger.error(f"{ticker}: 缓存加载失败 - {str(e)}")
            return None
    
    def clear_cache(self, ticker=None):
        """清除缓存"""
        if ticker:
            cache_file = self._get_cache_file(ticker)
            if cache_file.exists():
                cache_file.unlink()
                if ticker in self.metadata:
                    del self.metadata[ticker]
                self._save_metadata()
                logger.info(f"{ticker}: 缓存已清除")
        else:
            # 清除全部缓存
            import shutil
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.metadata = {}
            self._save_metadata()
            logger.info("全部缓存已清除")


if __name__ == "__main__":
    # 测试
    fetcher = DataFetcher()
    
    # 获取单只股票
    aapl = fetcher.fetch_historical_data('AAPL', start_date='2024-01-01')
    print(f"\nAAPL 数据 ({len(aapl)} 行):")
    print(aapl.head())
    
    # 批量获取
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    batch_data = fetcher.fetch_batch(tickers)
    print(f"\n批量获取完成，共 {len(batch_data)} 只股票")
