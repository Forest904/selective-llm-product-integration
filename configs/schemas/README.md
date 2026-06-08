# Schema Configs

`mediated_schema.json` defines the M1 product schema contract used by later
schema alignment, linkage, and fusion stages.

Required mediated attributes:

- `title`
- `brand`
- `model_number`
- `category`
- `description`
- `price`
- `currency`
- `specifications`

Long-tail product properties belong under `specifications` as traceable claims
rather than becoming one column per source attribute. Validate the schema with:

```bash
uv run mosaic schema validate --schema configs/schemas/mediated_schema.json
```
