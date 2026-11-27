# Data acquisition: bringing your own data

**Data → Data acquisition** lets you work with data the platform did not generate: weather-station exports,
data-logger files, soil-probe records, or data obtained from IMD or another agency.

## Upload

Click **Choose a CSV, Excel or JSON file**, then fill in:

- **Where the data comes from**: measured, simulated or computed from real data. Results built from this
  dataset carry that label (*Real*, *Synthetic* or *Derived data*), so declare it accurately.
- **Source and licence**: how you would cite the data in a paper.

Accepted formats (up to 50 MB and 200,000 rows):

| Format | Notes |
| --- | --- |
| CSV or TXT | Comma, semicolon, tab or pipe separated; UTF-8 or Windows encoding; decimal commas such as `0,25` are understood |
| Excel `.xlsx` | The first sheet is read; choose another sheet on the dataset page. Old `.xls` files must be saved as `.xlsx` or CSV first |
| JSON | A list of records, an object holding one list of records, or an object of equal-length arrays |

Dates and times are recognised in ISO form (`2026-02-10 06:15`) and day-first form (`10/02/2026 06:15`, common in
India), among others. The platform picks the format that reads the most values in the column.

The original file is stored unchanged in the platform's data folder. Its SHA-256 fingerprint is shown, so a
paper's data statement can identify the exact file used.

## Columns and mapping

The dataset page shows each column's type (date and time, number, text), missing values, range and examples.
Under **What the columns mean**, confirm or correct the platform's guess:

- **Date and time:** the column holding the reading time.
- **Sensor or station name:** only needed if one file holds several sensors.
- Either **one column per measurement** (each numeric column mapped to soil moisture, air temperature, relative
  humidity or rain), or **a variable column and a value column** (long format).
- Optionally, the **soil moisture at which the crop starts water stress**. Without it, soil readings are
  validated and reduced but raise no stress alerts. The Smart irrigation page shows a field's threshold.

Click **Save mapping**.

## Data quality

For each mapped series (one sensor, one variable), the report lists:
- the period covered and the usual reading interval;
- missing values;
- gaps (pauses longer than three times the usual interval);
- repeated timestamps;
- values outside physical limits.

It also counts rows that exactly duplicate another row. Nothing is changed in the file; the report tells you
what a reviewer of the data would ask about.

## Using the data

- **Run the retrieval framework** opens the Data retrieval framework page with this dataset selected. The data
  goes through the same validation, alerts, early warnings, reduction and task emission as simulated or device
  data.
- **Export tidy CSV** gives the mapped data in long form (`time, source, metric, value`), ready for R, Python or
  Excel pivot tables.
- **Original file** downloads the file exactly as uploaded.
