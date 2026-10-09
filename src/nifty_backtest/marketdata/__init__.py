"""Market data (M1-M2).

Downloads NSE end-of-day files, normalises the legacy and UDiFF bhavcopy formats into one
schema, stores them as Parquet for DuckDB, and derives the trading calendar, expiries and lot
sizes from the data itself.
"""
