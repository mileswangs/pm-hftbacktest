from __future__ import annotations

import chdb

from setup_local_chdb_weather import DB_PATH, load_snapshots_and_backtests


def _exec(query: str) -> str:
    conn = chdb.connect(str(DB_PATH))
    return conn.query(query)


def main() -> None:
    _exec("TRUNCATE TABLE pm_weather.pmxt_weather_entry_snapshots")
    _exec("TRUNCATE TABLE pm_weather.pmxt_weather_backtests")
    load_snapshots_and_backtests()
    print(
        _exec(
            """
            SELECT
                (SELECT count() FROM pm_weather.pmxt_weather_entry_snapshots) AS snapshot_rows,
                (SELECT count() FROM pm_weather.pmxt_weather_backtests) AS backtest_rows
            FORMAT Vertical
            """
        )
    )


if __name__ == "__main__":
    main()
