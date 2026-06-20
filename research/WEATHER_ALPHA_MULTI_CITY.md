# Multi-City Weather Alpha

Date checked: `2026-06-19`

Backtest window:

- anchor date: `2026-06-19`
- days: `17`
- entry hours tested: `6, 12, 18, 24, 36`
- strategy:
  - if one bucket probability > `50%`, buy it
  - otherwise buy the top two buckets if their combined probability > `50%`

Representative command:

```bash
python3 research/multi_city_weather_scan.py \
  --anchor-date 2026-06-19 \
  --days 17 \
  --entry-hours 6,12,18,24,36 \
  --cities chengdu,beijing,shanghai,guangzhou,tokyo,seoul,singapore,los-angeles,london,paris,taipei
```

## Best entry hour by city

| city | best hour | traded | hit rate | total pnl | avg pnl |
| --- | ---: | ---: | ---: | ---: | ---: |
| Chengdu | 12h | 17 | 76.5% | 2.550 | 0.150 |
| Seoul | 36h | 15 | 73.3% | 2.105 | 0.140 |
| Paris | 36h | 15 | 80.0% | 2.020 | 0.135 |
| Los Angeles | 6h | 16 | 81.2% | 1.560 | 0.097 |
| Tokyo | 6h | 17 | 100.0% | 1.378 | 0.081 |
| Singapore | 6h | 17 | 82.4% | 0.987 | 0.058 |
| Guangzhou | 12h | 13 | 61.5% | 0.380 | 0.029 |
| Taipei | 6h | 17 | 88.2% | 0.183 | 0.011 |
| Shanghai | 36h | 15 | 60.0% | -0.145 | -0.010 |
| Beijing | 6h | 17 | 58.8% | -1.935 | -0.114 |
| London | 36h | 15 | 53.3% | -2.025 | -0.135 |

## Main conclusion

The Chengdu result does **not** generalize as a universal `12h` weather alpha.

- `12h` works well in Chengdu and is still positive in Paris, Singapore, Los Angeles, and Guangzhou
- `12h` is roughly flat in Seoul and Taipei
- `12h` is clearly negative in Beijing, London, Shanghai, and Tokyo

Observed pattern:

- warmer, more persistent climates often favored shorter lead times (`6h` or `12h`)
- some cities with slower-moving temperature uncertainty favored longer lead times (`36h`)
- the signal is city-specific enough that a single global entry hour is a weak design

## Practical implication

If this strategy is pursued further, it should be parameterized per city or per climate regime rather than treated as a global weather alpha.
