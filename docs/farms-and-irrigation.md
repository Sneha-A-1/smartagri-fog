# Farms, weather and irrigation advice

Phase 2 starts the farm side of the platform. You describe your farms and fields once; the weather, irrigation and
(later) digital-twin and device pages build on them.

## Farms and fields

1. **Farms → New farm.** Click the farm's location on the map (or type its coordinates), give a name, and an
   approximate elevation.
2. Open the farm and click **Draw a field**. Click the field's corners on the satellite map, then **Finish field**.
   The area is calculated from the boundary.
3. In the panel on the right, set the field's **crop**, **sowing date**, **soil texture** and **irrigation method**
   (or tick *Rainfed*). Under *Crop details* you can change the root depth and the length of the four growth stages.

Crop and soil defaults:

| Setting | Source |
| --- | --- |
| Crop coefficients Kc (initial, mid-season, end) | FAO-56 Table 12 |
| Root depth and depletion fraction p | FAO-56 Table 22 |
| Growth-stage lengths | Typical values for India; edit them per variety and season (see FAO-56 Table 11) |
| Yield response factor Ky | FAO Irrigation and Drainage Paper 33 (not published for rice, chickpea and mustard) |
| Soil field capacity and wilting point | Midpoints of the ranges in FAO-56 Table 19 |
| Irrigation efficiency | Typical values: surface 60%, sprinkler 75%, drip 90% (editable) |

## Weather

**Weather & climate** shows daily weather for a farm from one of three sources:

| Source | Data origin | Notes |
| --- | --- | --- |
| Open-Meteo | Real | Free, no account needed. ERA5 reanalysis for past dates, weather models for recent days and the 7-day forecast. Needs an internet connection; downloaded days are cached in the database. |
| Imported station CSV | Real | For data from a weather station or IMD. Choose *My imported station data*, then **Import station CSV**. The page lists the columns. |
| Synthetic | Synthetic | Invented, seeded weather for demos and offline use. Results are labelled *Synthetic data*. |

Reference evapotranspiration (ET₀) is computed by the platform with the FAO-56 Penman-Monteith equation. With
Open-Meteo data, the page also shows Open-Meteo's own ET₀ and the average difference between them. When solar
radiation is missing (common in station data), it is estimated from the daily temperature range (FAO-56 eq. 50),
and the page says so.

## Smart irrigation

**Smart irrigation** runs a daily FAO-56 soil-water balance for a field from its sowing date to today, plus the
forecast:

- The crop's water use is ET₀ × Kc, following the crop's growth stages.
- The root zone holds the soil's usable water (field capacity minus wilting point) over the root depth. The crop
  is stressed when more than the fraction p of it is used, and then uses less water.
- Irrigation is advised when the depletion reaches that point. The advice gives the amount that reaches the roots
  and the amount to apply at the field's efficiency. Using the forecast, it says how many days remain until the
  next irrigation.

The page reports season totals: crop water need and actual use, rain (and how much of it was useful), irrigation,
water lost below the roots, days with stress, and the expected relative yield (FAO-33).

### Validation

`packages/core/tests/test_agro.py` checks the implementation against FAO-56's worked examples. Example 18 (Uccle,
6 July) gives ET₀ = 3.88 mm/day, against 3.9 published, and every intermediate value matches: Rₐ 41.09, Rₛ 22.07,
Rₙ 13.28, eₛ 1.997, eₐ 1.409. Example 8 gives Rₐ = 32.2 MJ m⁻² day⁻¹. The water balance conserves water exactly over
a season. With irrigation at the threshold the crop is never stressed; a rainfed sandy field shows stress and
yield loss.

### Assumptions

The page lists them under *Method and assumptions*:
- The soil starts at field capacity.
- The root depth is fixed, with no capillary rise.
- Rain below 20% of ET₀ is lost to interception.
- Water above field capacity drains on the same day.
- Irrigation refills the root zone to field capacity.

These are standard simplifications of the FAO-56 single-coefficient method. Pump and valve control, soil-moisture
sensor readings and the digital-twin map come in the next part of Phase 2.
