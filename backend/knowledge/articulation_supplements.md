# Articulation Supplements — Additional Technical Details

## IoT & Sensor Infrastructure Specifications

### Proposed Sensor Network Architecture
Alt Carbon's sensor-augmented MRV system will deploy the following instrumentation across representative ERW and biochar deployment sites:

### Soil Sensors
- **Soil moisture probes**: METER TEROS 12 — capacitance-based, ±3% accuracy, 0–100% VWC range, SDI-12 output
- **Soil temperature sensors**: METER TEROS 12 (integrated) — ±0.5°C accuracy, -40 to 60°C range
- **Soil pH sensors**: Van London pHoenix pH electrode — gel-filled, field-grade, ±0.02 pH accuracy
- **Electrical conductivity**: METER TEROS 12 (integrated) — bulk EC measurement, 0–20 dS/m range
- **Soil CO₂ flux chambers**: LI-COR LI-8100A automated soil CO₂ flux system for measuring soil respiration and CO₂ efflux rates

### Water Chemistry Sensors
- **Porewater samplers**: Rhizon MOM macrorhizons at 30 cm depth — 0.15 µm pore size, passive extraction
- **Water pH/EC multi-parameter probes**: YSI ProDSS — measures pH, conductivity, temperature, dissolved oxygen, ORP
- **Alkalinity titration kits**: Hach AL-DT digital titrator for field-grade alkalinity measurements (relevant to DIC flux)
- **Water level loggers**: Onset HOBO U20L for groundwater table monitoring — ±0.1% accuracy, 10-year battery

### Weather & Environmental
- **Weather stations**: METER ATMOS 41 all-in-one — measures solar radiation, air temperature, humidity, rainfall, wind speed/direction, barometric pressure, vapor pressure
- **Rain gauges**: METER ECRN-100 tipping bucket — 0.2mm resolution, ±2% accuracy
- **River discharge monitoring**: stage-height loggers with calibrated rating curves at key catchment outlets

### IoT Infrastructure
- **Data loggers**: METER ZL6 (6-port) — cellular-enabled, MQTT/HTTP push, solar-powered, IP67 rated
- **Connectivity**: 4G LTE cellular via embedded SIM, with LoRaWAN mesh backup for remote Darjeeling plots
- **Edge computing**: Raspberry Pi 4-based edge nodes for local data QA, anomaly detection, and store-and-forward
- **Cloud pipeline**: Sensor data → MQTT broker → AWS IoT Core → Feluda data layer → ATLAS / The Observatory
- **Sampling frequency**: Soil sensors at 15-minute intervals, weather at 5-minute intervals, water chemistry weekly to biweekly

### Deployment Scale
- **Phase 1 (Months 1-6)**: 20 instrumented plots across 3 agro-climatic zones (Darjeeling tea, Eastern India rice, mixed cropping)
- **Phase 2 (Months 7-12)**: Expand to 50 plots, add water monitoring network
- **Estimated total sensor units**: ~400 soil probes, 50 weather stations, 80 porewater samplers, 60 water quality probes
- **Per-plot cost**: ~$2,500–4,000 (sensors + logger + installation + connectivity)
- **Total sensor infrastructure budget**: ~$150,000–200,000

## Biochar Unit Economics

### Current Biochar Cost Structure
Alt Carbon's biochar pathway operates through centralized pyrolysis with distributed biomass sourcing:

| Cost Component | Current Cost ($/tCO₂) | Notes |
|---|---:|---|
| Biomass procurement & aggregation | 25 | Hub-and-spoke model, pre-secured feedstock from 40,000+ acres |
| Transportation (biomass to plant) | 18 | Average 50km radius collection zone |
| Pyrolysis (energy + operations) | 35 | 15 TPD pilot; target 80 TPD commercial |
| Biochar transportation & application | 12 | Leverages existing ERW logistics fleet |
| Sampling, testing & MRV | 20 | Shared D-CAL infrastructure with ERW |
| Overhead & G&A | 15 | Shared with ERW operations |
| **Total current cost** | **$125/tCO₂** | At pilot scale (15 TPD) |

### Projected Biochar Cost Trajectory
| Scale Stage | Cost ($/tCO₂) | Plant Capacity |
|---|---:|---|
| Current pilot | 125 | 15 TPD |
| First commercial (2026) | 95 | 2 × 80 TPD plants |
| Full scale (2027-2028) | 65 | 6 × 80 TPD plants |

### Key Cost Reduction Levers
1. **Plant scale**: 15 TPD → 80 TPD reduces pyrolysis cost from $35 to ~$18/tCO₂ through fixed-cost amortization
2. **Biomass aggregation density**: More plants in Eastern India reduce avg collection radius from 50km to 30km
3. **Shared MRV**: D-CAL and Feluda serve both ERW and biochar, reducing marginal MRV cost to ~$8/tCO₂ at scale
4. **Carbon content optimization**: Target biochar with >70% fixed carbon content for higher per-tonne credit value

### Biochar Carbon Accounting
- **Fixed carbon content**: 65-75% (measured via proximate analysis at D-CAL)
- **Permanence**: BC+100 methodology — >100-year permanence for biochar with H/Corg < 0.4
- **Conversion factor**: ~3.0–3.5 tonnes biomass per tonne CO₂ equivalent stored
- **Current credit pricing**: $150–200/tCO₂ (biochar credits, pre-issuance)
- **Registry pathway**: Puro.earth biochar methodology, with Isometric cross-verification planned

## Laser Ablation — Additional Technical Specifications

### LaserTRAX193 Core System — Detailed Capabilities
- **Laser type**: ArF excimer, 193 nm wavelength
- **Repetition rate**: 1–300 Hz
- **Spot sizes**: 5–200 µm (adjustable)
- **Optimal ERW spot size**: 20–50 µm for soil mineral phase identification
- **Ablation modes**: Line scan, spot analysis, mapping
- **Sample throughput**: 40–60 samples per 8-hour shift (vs 8–12 for wet chemistry)
- **Elements of interest for ERW**: Ca, Mg, Na, K, Si, Al, Fe, Mn, Sr, Ba, Ti, Cr, Ni (major and trace)
- **Detection limits**: Sub-ppm for most elements (comparable to solution ICP-MS for matrix-matched standards)

### Calibration Strategy
- **Matrix-matched standards**: NIST SRM 612/610, USGS basalt standards (BCR-2, BHVO-2), and in-house pressed pellets from D-CAL reference soils
- **Internal standardization**: Using Si or Ca as internal standard elements
- **QA/QC protocol**: Every 20 unknowns bracketed by 2 standards + 1 blank + 1 duplicate
- **Data reduction**: Iolite software for time-resolved signal processing, drift correction, and uncertainty propagation
