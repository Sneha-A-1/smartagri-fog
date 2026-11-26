"""FAO-56 reference evapotranspiration and root-zone soil-water balance.

R. G. Allen, L. S. Pereira, D. Raes, M. Smith. Crop evapotranspiration: Guidelines for computing crop water
requirements. FAO Irrigation and Drainage Paper 56, Rome, 1998. Equation numbers below refer to it.

Daily time step throughout: temperatures in deg C, radiation in MJ m-2 day-1, wind in m s-1, vapour pressure
in kPa, water depths in mm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

SIGMA = 4.903e-9  # Stefan-Boltzmann constant, MJ K-4 m-2 day-1
GSC = 0.0820  # solar constant, MJ m-2 min-1


def sat_vapour_pressure(t: float) -> float:
    """e°(T), eq. 11."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def vapour_slope(t: float) -> float:
    """Slope of the saturation vapour pressure curve, eq. 13."""
    return 4098 * sat_vapour_pressure(t) / (t + 237.3) ** 2


def atmospheric_pressure(elevation_m: float) -> float:
    """Eq. 7."""
    return 101.3 * ((293 - 0.0065 * elevation_m) / 293) ** 5.26


def psychrometric_constant(pressure_kpa: float) -> float:
    """Eq. 8."""
    return 0.000665 * pressure_kpa


def wind_at_2m(speed: float, height_m: float) -> float:
    """Convert wind measured at ``height_m`` to 2 m, eq. 47."""
    return speed * 4.87 / math.log(67.8 * height_m - 5.42)


def extraterrestrial_radiation(lat_deg: float, doy: int) -> tuple[float, float]:
    """Ra (eq. 21) and daylight hours N (eq. 34) for a latitude and day of year."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    delta = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    ra = (
        24
        * 60
        / math.pi
        * GSC
        * dr
        * (ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))
    )
    return ra, 24 / math.pi * ws


def actual_vapour_pressure(
    tmin: float, tmax: float, rh_min: float | None = None, rh_max: float | None = None, rh_mean: float | None = None
) -> float:
    """ea from RHmax and RHmin (eq. 17), from RHmean (eq. 19), or from Tmin as dew point (eq. 48)."""
    if rh_min is not None and rh_max is not None:
        return (sat_vapour_pressure(tmin) * rh_max / 100 + sat_vapour_pressure(tmax) * rh_min / 100) / 2
    es = (sat_vapour_pressure(tmax) + sat_vapour_pressure(tmin)) / 2
    if rh_mean is not None:
        return rh_mean / 100 * es
    return sat_vapour_pressure(tmin)


@dataclass(frozen=True)
class Et0Result:
    et0: float
    rs: float
    rs_estimated: bool
    ra: float
    rn: float
    es: float
    ea: float
    delta: float
    gamma: float


def et0_penman_monteith(
    *,
    tmax: float,
    tmin: float,
    lat_deg: float,
    elevation_m: float,
    doy: int,
    u2: float | None = None,
    rs: float | None = None,
    sunshine_hours: float | None = None,
    rh_min: float | None = None,
    rh_max: float | None = None,
    rh_mean: float | None = None,
    krs: float = 0.16,
    albedo: float = 0.23,
) -> Et0Result:
    """FAO Penman-Monteith reference evapotranspiration (eq. 6), daily, with G = 0.

    Solar radiation: measured ``rs``, else from sunshine hours (Angstrom, eq. 35), else from the temperature
    range (Hargreaves, eq. 50, ``krs`` 0.16 interior, 0.19 coastal). Missing wind defaults to 2 m/s (FAO-56
    recommendation for missing data). Missing humidity falls back to Tmin as dew point (eq. 48).
    """
    tmean = (tmax + tmin) / 2
    pressure = atmospheric_pressure(elevation_m)
    gamma = psychrometric_constant(pressure)
    delta = vapour_slope(tmean)
    es = (sat_vapour_pressure(tmax) + sat_vapour_pressure(tmin)) / 2
    ea = actual_vapour_pressure(tmin, tmax, rh_min, rh_max, rh_mean)
    ra, daylight = extraterrestrial_radiation(lat_deg, doy)
    estimated = rs is None
    if rs is None:
        if sunshine_hours is not None:
            rs = (0.25 + 0.50 * sunshine_hours / daylight) * ra
        else:
            rs = krs * math.sqrt(max(tmax - tmin, 0.0)) * ra
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rns = (1 - albedo) * rs
    ratio = min(rs / rso, 1.0) if rso > 0 else 1.0
    rnl = (
        SIGMA
        * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4)
        / 2
        * (0.34 - 0.14 * math.sqrt(max(ea, 0)))
        * (1.35 * ratio - 0.35)
    )
    rn = rns - rnl
    u = 2.0 if u2 is None else u2
    et0 = (0.408 * delta * rn + gamma * 900 / (tmean + 273) * u * (es - ea)) / (delta + gamma * (1 + 0.34 * u))
    return Et0Result(max(et0, 0.0), rs, estimated, ra, rn, es, ea, delta, gamma)


# --- crops and soils --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Crop:
    key: str
    name: str
    kc_ini: float  # FAO-56 Table 12
    kc_mid: float
    kc_end: float
    stages: tuple[int, int, int, int]  # initial, development, mid, late (days); editable defaults
    root_depth_m: float  # FAO-56 Table 22 (upper end of the range for the maximum rooting depth)
    p: float  # depletion fraction for no stress, FAO-56 Table 22 (for ETc ~ 5 mm/day)
    ky: float | None  # seasonal yield response factor, FAO-33 (Doorenbos & Kassam, 1979)

    @property
    def season_days(self) -> int:
        return sum(self.stages)

    def kc(self, day: int) -> float:
        """Single crop coefficient on day ``day`` (0-based) of the season: FAO-56 Figure 25."""
        ini, dev, mid, late = self.stages
        if day < ini:
            return self.kc_ini
        if day < ini + dev:
            return self.kc_ini + (day - ini + 1) / dev * (self.kc_mid - self.kc_ini)
        if day < ini + dev + mid:
            return self.kc_mid
        if day < ini + dev + mid + late:
            return self.kc_mid + (day - ini - dev - mid + 1) / late * (self.kc_end - self.kc_mid)
        return self.kc_end


# Stage lengths are typical values for the Indian subcontinent and are meant to be edited per field; check
# FAO-56 Table 11 and local agronomic guidance for your variety and season.
CROPS: dict[str, Crop] = {
    c.key: c
    for c in [
        Crop("wheat", "Wheat (rabi)", 0.30, 1.15, 0.30, (20, 25, 50, 30), 1.5, 0.55, 1.05),
        Crop("rice", "Rice (paddy)", 1.05, 1.20, 0.75, (30, 30, 60, 30), 0.5, 0.20, None),
        Crop("maize", "Maize (grain)", 0.30, 1.20, 0.50, (20, 35, 40, 30), 1.0, 0.55, 1.25),
        Crop("cotton", "Cotton", 0.35, 1.15, 0.60, (30, 50, 55, 45), 1.0, 0.65, 0.85),
        Crop("sugarcane", "Sugarcane", 0.40, 1.25, 0.75, (35, 60, 190, 120), 1.2, 0.65, 1.20),
        Crop("potato", "Potato", 0.50, 1.15, 0.75, (25, 30, 45, 30), 0.4, 0.35, 1.10),
        Crop("tomato", "Tomato", 0.60, 1.15, 0.80, (30, 40, 40, 25), 0.7, 0.40, 1.05),
        Crop("soybean", "Soybean", 0.40, 1.15, 0.50, (15, 15, 40, 15), 0.6, 0.50, 0.85),
        Crop("groundnut", "Groundnut", 0.40, 1.15, 0.60, (25, 35, 45, 25), 0.5, 0.50, 0.70),
        Crop("chickpea", "Chickpea (gram)", 0.40, 1.00, 0.35, (20, 30, 40, 20), 0.6, 0.50, None),
        Crop("mustard", "Mustard (rapeseed)", 0.35, 1.10, 0.35, (25, 35, 45, 25), 1.0, 0.60, None),
        Crop("onion", "Onion (dry)", 0.70, 1.05, 0.75, (15, 25, 70, 40), 0.3, 0.30, 1.10),
    ]
}


@dataclass(frozen=True)
class Soil:
    key: str
    name: str
    field_capacity: float  # m3/m3, midpoint of the FAO-56 Table 19 range
    wilting_point: float

    @property
    def taw_per_m(self) -> float:
        return 1000 * (self.field_capacity - self.wilting_point)


SOILS: dict[str, Soil] = {
    s.key: s
    for s in [
        Soil("sand", "Sand", 0.12, 0.045),
        Soil("loamy_sand", "Loamy sand", 0.15, 0.065),
        Soil("sandy_loam", "Sandy loam", 0.23, 0.11),
        Soil("loam", "Loam", 0.25, 0.12),
        Soil("silt_loam", "Silt loam", 0.29, 0.15),
        Soil("silt", "Silt", 0.32, 0.17),
        Soil("silty_clay_loam", "Silty clay loam", 0.335, 0.205),
        Soil("silty_clay", "Silty clay", 0.36, 0.23),
        Soil("clay", "Clay", 0.36, 0.22),
    ]
}


# --- water balance ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class DayWeather:
    day: date
    et0: float
    rain: float = 0.0
    forecast: bool = False


@dataclass
class IrrigationPolicy:
    """When to irrigate. ``trigger`` is the depletion fraction of TAW that triggers irrigation (None = the crop's
    adjusted p, i.e. just before stress); irrigation refills to field capacity. ``rainfed`` disables it."""

    rainfed: bool = False
    trigger: float | None = None
    efficiency: float = 0.75  # application efficiency: gross = net / efficiency
    min_rain_fraction: float = 0.2  # rain below this fraction of ET0 is lost to interception (FAO-56 ch. 8)


@dataclass
class BalanceDay:
    day: date
    stage_day: int
    et0: float
    kc: float
    etc: float
    etc_adj: float
    ks: float
    rain: float
    effective_rain: float
    irrigation_net: float
    irrigation_gross: float
    deep_percolation: float
    depletion: float  # Dr at the end of the day, mm
    taw: float
    raw: float
    p: float
    forecast: bool
    model_depletion: float | None = None  # before correction, on days with a sensor observation
    correction: float = 0.0  # observed minus modelled depletion, mm (positive: drier than modelled)


@dataclass
class BalanceResult:
    days: list[BalanceDay] = field(default_factory=list)

    def summary(self, crop: Crop) -> dict[str, float | int | None]:
        past = [d for d in self.days if not d.forecast]
        etc = sum(d.etc for d in past)
        eta = sum(d.etc_adj for d in past)
        rel = (1 - crop.ky * (1 - eta / etc)) if crop.ky is not None and etc > 0 else None
        return {
            "days": len(past),
            "et0_mm": sum(d.et0 for d in past),
            "etc_mm": etc,
            "eta_mm": eta,
            "rain_mm": sum(d.rain for d in past),
            "effective_rain_mm": sum(d.effective_rain for d in past),
            "irrigation_net_mm": sum(d.irrigation_net for d in past),
            "irrigation_gross_mm": sum(d.irrigation_gross for d in past),
            "irrigation_events": sum(1 for d in past if d.irrigation_net > 0),
            "deep_percolation_mm": sum(d.deep_percolation for d in past),
            "stress_days": sum(1 for d in past if d.ks < 1),
            "sensor_days": sum(1 for d in past if d.model_depletion is not None),
            "sensor_correction_mm": sum(d.correction for d in past),
            "relative_yield": max(0.0, rel) if rel is not None else None,
        }


def adjusted_p(p_table: float, etc: float) -> float:
    """FAO-56 Table 22 footnote: p = p_table + 0.04 (5 - ETc), limited to 0.1-0.8."""
    return min(0.8, max(0.1, p_table + 0.04 * (5 - etc)))


@dataclass(frozen=True)
class Step:
    etc: float
    etc_adj: float
    ks: float
    effective_rain: float
    deep_percolation: float
    depletion: float
    p: float
    raw: float


def day_step(
    dr: float, w: DayWeather, crop: Crop, n: int, taw: float, policy: IrrigationPolicy, irr_net: float
) -> Step:
    """One day of FAO-56 eq. 85 starting from depletion ``dr`` with ``irr_net`` mm applied in the morning."""
    kc = crop.kc(n)
    etc = kc * w.et0
    p = adjusted_p(crop.p, etc)
    raw = p * taw
    eff_rain = w.rain if w.rain >= policy.min_rain_fraction * w.et0 else 0.0
    start = dr - irr_net  # depletion after the morning irrigation drives today's stress (eq. 84)
    ks = 1.0 if start <= raw else max(0.0, (taw - start) / ((1 - p) * taw)) if taw > 0 else 0.0
    etc_adj = ks * etc
    new = dr - eff_rain - irr_net + etc_adj
    return Step(etc, etc_adj, ks, eff_rain, max(0.0, -new), min(max(new, 0.0), taw), p, raw)


def water_balance(
    weather: list[DayWeather],
    crop: Crop,
    soil: Soil,
    sowing: date,
    *,
    root_depth_m: float | None = None,
    policy: IrrigationPolicy | None = None,
    initial_depletion: float = 0.0,
    observations: dict[date, float] | None = None,
) -> BalanceResult:
    """Daily root-zone depletion (FAO-56 eq. 85) with the single crop coefficient and water stress (eq. 84).

    Simplifications (documented): fixed root depth, no capillary rise, no runoff beyond the interception
    threshold; water above field capacity drains as deep percolation the same day.
    Irrigation is applied at the start of a day when the previous day's depletion reached the trigger.

    ``observations`` maps days to measured end-of-day depletion (from soil-moisture sensors). On those days the
    modelled depletion is replaced by the measurement (direct insertion), and the difference is recorded, so the
    water balance closes as: change in depletion = ETa - rain - irrigation + drainage + corrections.
    """
    policy = policy or IrrigationPolicy()
    zr = root_depth_m or crop.root_depth_m
    taw = soil.taw_per_m * zr
    dr = min(max(initial_depletion, 0.0), taw)
    out = BalanceResult()
    for w in sorted(weather, key=lambda x: x.day):
        n = (w.day - sowing).days
        if n < 0:
            continue
        kc = crop.kc(n)
        p = adjusted_p(crop.p, kc * w.et0)
        trigger = (policy.trigger if policy.trigger is not None else p) * taw
        irr_net = dr if (not policy.rainfed and not w.forecast and dr >= trigger and dr > 0) else 0.0
        st = day_step(dr, w, crop, n, taw, policy, irr_net)
        etc, etc_adj, ks, eff_rain, dp, raw = st.etc, st.etc_adj, st.ks, st.effective_rain, st.deep_percolation, st.raw
        dr = st.depletion
        model_dr, correction = None, 0.0
        if observations and w.day in observations and not w.forecast:
            model_dr = dr
            dr = min(max(observations[w.day], 0.0), taw)
            correction = dr - model_dr
        out.days.append(
            BalanceDay(
                w.day,
                n,
                w.et0,
                kc,
                etc,
                etc_adj,
                ks,
                w.rain,
                eff_rain,
                irr_net,
                irr_net / policy.efficiency if irr_net else 0.0,
                dp,
                dr,
                taw,
                raw,
                p,
                w.forecast,
                model_dr,
                correction,
            )
        )
        if n >= crop.season_days - 1:
            break
    return out


def recommendation(result: BalanceResult, policy: IrrigationPolicy | None = None) -> dict[str, object]:
    """Advice for the last observed day, using any forecast days after it."""
    policy = policy or IrrigationPolicy()
    past = [d for d in result.days if not d.forecast]
    if not past:
        return {"action": "none", "text": "No observed days in the season yet."}
    today = past[-1]
    trigger = (policy.trigger if policy.trigger is not None else today.p) * today.taw
    if policy.rainfed:
        return {
            "action": "rainfed",
            "text": "Rainfed field: no irrigation is scheduled.",
            "depletion_mm": today.depletion,
        }
    if today.depletion >= trigger:
        gross = today.depletion / policy.efficiency
        return {
            "action": "irrigate",
            "net_mm": today.depletion,
            "gross_mm": gross,
            "depletion_mm": today.depletion,
            "text": f"Irrigate now: about {today.depletion:.0f} mm reaches the roots ({gross:.0f} mm applied at "
            f"{policy.efficiency:.0%} efficiency).",
        }
    dr, days = today.depletion, None
    for i, d in enumerate([x for x in result.days if x.forecast], start=1):
        dr = max(0.0, dr - d.effective_rain) + d.etc_adj
        if dr >= trigger:
            days = i
            break
    if days is None:
        text = "No irrigation needed during the forecast period."
    else:
        text = f"No irrigation needed today; the forecast reaches the irrigation point in about {days} day(s)."
    return {"action": "wait", "days_until": days, "depletion_mm": today.depletion, "trigger_mm": trigger, "text": text}
