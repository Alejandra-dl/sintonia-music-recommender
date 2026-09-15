# Sample data (synthetic)

`raw/Streaming_History_Audio_sample.json` contains **28 completely fictitious records**. Artists,
track titles and URIs are invented, and the IP address belongs to the reserved documentation range
(`192.0.2.0/24`, RFC 5737). No record comes from a real listening history.

The file follows the field structure of Spotify's *Extended Streaming History* export and deliberately
includes the edge cases the ETL handles: one exact duplicate, one 0 ms play, one podcast episode,
one play outside the selected date range and sensitive fields (`ip_addr`, `offline_timestamp`) that are
removed during data minimisation.

It is meant to show the input format and to run the ETL step. It is **too small to train the model
or produce meaningful recommendations**, and no result shown in the main README comes from it.

```bash
PYTHONPATH=src python -m asistente.etl.spotify --usuario demo \
    --input sample_data/raw --min-date 2019-01-01
```

Expected quality report: 28 raw records → 24 clean plays (1 duplicate, 1 zero-length play,
1 podcast and 1 out-of-range record removed).
