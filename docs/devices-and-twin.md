# Devices, sensor-corrected irrigation and the digital twin

## IoT devices

**IoT devices** lists the devices on each farm and shows their readings. Click **Add device**, click the device's
position on the map, and choose its type:

| Type | Readings | Attached to |
| --- | --- | --- |
| Soil-moisture sensor | Volumetric water content of the root zone (m³/m³) | A field |
| Weather station | Air temperature, relative humidity, rain | The farm (optionally a field) |
| Irrigation valve | Open (1) or closed (0) | A field |
| Gateway | None yet; marks where the farm's network connects | The farm |

A device is **simulated** or **real hardware**.

### Simulated devices

Simulated devices generate their readings on demand, up to the current minute, whenever a page asks for them. The
same device and time always give the same reading, so history is reproducible. All simulated readings are labelled
*Synthetic data*.

- A **soil-moisture sensor** measures a "true" field: the FAO-56 water balance of the field, with crop water use set
  to a percentage of the FAO-56 estimate (115% by default), because real fields rarely match the model. The sensor
  adds noise (0.01 m³/m³ by default) and misses a small share of readings.
- A **valve** opens at 06:00 on the true field's irrigation days, for the time needed to apply the water at 5 mm/h.
- A **weather station** reports hourly values derived from the farm's daily weather: temperature on a daily cycle
  between the minimum at 06:00 and the maximum at 15:00, humidity, and the day's rain.

Simulated days follow local solar time, which in India is within about 25 minutes of IST.

### Real devices

When you add a real device, the platform shows a **token** once. The device sends readings as JSON over HTTP:

```http
POST http://<platform address>:8000/api/ingest
X-Device-Token: <token>
Content-Type: application/json

{"device_id": "<device id>", "readings": [{"metric": "soil_moisture_m3m3", "value": 0.21}]}
```

`ts` (an ISO time) is optional for each reading; without it, the time of receipt is used. Duplicate readings (same
device, metric and time) are ignored. The page shows a PowerShell command you can run to test this.

On an ESP32 (Arduino), the request is a few lines with the `HTTPClient` library: set the two headers and post the JSON
body above. Calibrate capacitive soil probes against oven-dried samples of your soil before trusting absolute values.

**Network access.** The platform normally listens only on your laptop (`127.0.0.1`), so devices on the farm network
cannot reach it. For a test you can start it with `uv run smartagri-api --host 0.0.0.0`. In local mode there is no
login, so anyone on that network could then use the whole platform. Do this only on a network you trust, and only
while testing. Server mode with logins is for deployments.

MQTT is not implemented yet; the HTTP endpoint above is what exists today.

## Sensor-corrected irrigation

On **Smart irrigation**, tick **Correct with soil-moisture sensors**. On every day with readings, the FAO-56 model's
root-zone depletion is replaced by the one measured by the field's sensors: the mean soil moisture after 21:00,
converted with the soil's field capacity and the root depth. The chart shows the model's own value as a dotted line,
and the season summary reports the sum of the corrections. The digital twin uses the same correction by default.

## Digital twin & map

**Digital twin & map** shows every farm on one satellite map:

- Fields are coloured by the share of usable root-zone water still available: green above 65%, yellow below
  that, red when irrigation is due or the crop is stressed, and grey without a sowing date.
- Devices are shown in their type's colour, or grey when offline (no reading for three intervals).
- Hovering over a device shows its latest readings.
- You can switch the fields, sensors, actuators and network layers on and off.

The page refreshes every minute. Clicking a field shows its advice and links to its irrigation details.

## Case study: is a soil-moisture sensor worth it?

**Algorithm catalogue → Experiment: model-only vs sensor-assisted irrigation** runs a controlled experiment for a
paper. Over many seasons of synthetic weather, a farmer irrigates a field whose true water use differs from FAO-56,
deciding from one of four beliefs:

| Strategy | The farmer's belief about the root zone |
| --- | --- |
| Model only | The FAO-56 water balance |
| Sensor | Each evening's sensor reading replaces the model |
| Fused | A one-dimensional Kalman filter combining model and sensor according to their uncertainties |
| Oracle | The truth (upper bound) |

Yield (FAO-33), stress days, water applied, drainage below the roots and belief error are measured on the true
field. Every strategy faces the same seasons, and the results are compared with Friedman and Holm-corrected Wilcoxon
tests.

Default result (30 seasons, wheat on sandy loam, the field uses 120% of FAO-56, sensor noise 0.02 m³/m³):

| | Model only | Sensor | Fused | Oracle |
| --- | --- | --- | --- | --- |
| Relative yield | 0.95 | 1.00 | 0.97 | 1.00 |
| Stress days | 23 | 0.3 | 18 | 3.2 |
| Irrigation applied (mm) | 364 | 794 | 398 | 490 |
| Drainage below the roots (mm) | 3.6 | 170 | 3.6 | 4.5 |
| Mean belief error (mm) | 21.5 | 19.7 | 13.9 | 0 |

How to read it:
- **Model only** under-irrigates a thirsty field.
- **Sensor:** trusting a noisy probe outright prevents stress, but it triggers irrigation on noise and wastes
  water. With a 1.5 m root zone, ±0.02 m³/m³ is ±30 mm.
- **Fused:** the Kalman filter has the smallest belief error and wastes no water. It still allows some stress,
  because a basic filter corrects a consistent model bias only slowly; a filter that also estimates the bias
  would be a natural extension.

These numbers come from synthetic seasons and depend on the parameters. Vary the bias, the noise and the soil to
map out when sensing pays off.
