"""Live trading module (placeholder).

Planned components:
    - broker.py:    Broker adapter (IBKR / Alpaca API)
    - executor.py:  Order execution (diff current vs target, submit orders)
    - monitor.py:   Position monitoring + risk checks
    - scheduler.py: Cron scheduling (daily data update + signal + rebalance)

The live module reuses strategy/ for signal generation.
Execution is separated from backtesting.

Data flow:
    FMPDataLoader → Strategy.on_rebalance() → target_weights
                                                    ↓
                                  Executor: diff(current, target) → orders
                                                    ↓
                                  Broker: submit orders → fills
"""
