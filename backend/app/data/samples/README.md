# UCI Online Retail sample

`uci_online_retail_sample.csv` is a compact, derived test fixture from:

> Chen, D. (2015). *Online Retail* [Dataset]. UCI Machine Learning Repository.
> https://doi.org/10.24432/C5BW33

- Source page: https://archive.ics.uci.edu/dataset/352/online+retail
- License: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
- Original scope: 541,909 line items dated December 2010 through December 2011
- Original currency: GBP (sterling)

## Transformations

The generator streams the original XLSX, keeps rows with a source `CustomerID`,
aggregates product lines into invoices, interprets invoice numbers beginning
with `C` as cancellations, and chooses customers from lapsed, middle, and recent
recency thirds. The checked-in fixture contains:

- 60 pseudonymous customers;
- 1,510 invoice-level payments;
- at most 36 payments per selected customer; and
- 222 cancellation/refund records.

Generated display names such as `UCI Customer 12748` are labels created by
Churnary; they are not names from the source. No emails, phone numbers, card
details, addresses, or credentials are included. Favorite products are derived
from positive line-item value.

The stored CSV retains the original dates. The authenticated sample-import API
shifts every customer and transaction by one common offset so the latest event
is yesterday. This preserves all interpurchase intervals while making a
historical dataset useful for today's retention scoring.

## Reproduce

Download `Online Retail.xlsx` from the UCI source page, then run:

```bash
cd backend
uv run python -m app.scripts.uci_online_retail_demo \
  "/path/to/Online Retail.xlsx" \
  --customers 60 \
  --transactions-per-customer 36 \
  --fixture app/data/samples/uci_online_retail_sample.csv
```

Because the fixture is an adaptation, redistribution must retain attribution
under the source dataset's CC BY 4.0 license.
