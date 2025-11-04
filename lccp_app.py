import streamlit as st
import pandas as pd
from dataclasses import dataclass

# ----------------------------
# CONFIG / DEFAULT CONSTANTS
# ----------------------------
DEFAULT_LIFETIME_YEARS = 15
DEFAULT_COOLING_HOURS = 1000
DEFAULT_HEATING_HOURS = 600
DEFAULT_GRID_KGCO2_PER_KWH = 0.38
EMBODIED_KGCO2_PER_KG_MATERIAL = 5
DEFAULT_REFRIG_GWP = 675.0   # e.g. R-32 placeholder


# ----------------------------
# DATA CLASSES
# ----------------------------
@dataclass
class SystemInputs:
    capacity_btuh: float
    seer2: float
    hspf2: float
    refrigerant_charge_kg: float
    reclaimed_refrigerant_pct: float
    annual_leak_rate_pct: float
    eol_loss_pct: float
    material_weight_kg: float


@dataclass
class DirectCFInputs:
    reclaimed_per_unit_pct: float
    unit_volume_cuft: float
    manufactured_in_usa: bool
    leak_detectors: bool
    refrigerant_safety_class: str


@dataclass
class IndirectCFInputs:
    compressor_type: str
    demand_flex: bool
    connected_thermostat: bool


# ----------------------------
# CORE CALCS
# ----------------------------
def calc_baseline_direct(system: SystemInputs,
                         refrigerant_gwp: float,
                         lifetime_years: int,
                         embodied_factor: float) -> float:
    charge = system.refrigerant_charge_kg
    annual_leak_frac = system.annual_leak_rate_pct / 100.0
    eol_loss_frac = system.eol_loss_pct / 100.0

    # annual/leak
    annual_leak_kg = charge * annual_leak_frac
    total_leak_kg = annual_leak_kg * lifetime_years

    remaining_kg = max(charge - total_leak_kg, 0)
    eol_leak_kg = remaining_kg * eol_loss_frac

    refrigerant_emissions = (total_leak_kg + eol_leak_kg) * refrigerant_gwp

    # credit for reclaimed refrigerant used at initial charge
    reclaimed_frac = system.reclaimed_refrigerant_pct / 100.0
    reclaimed_credit = charge * reclaimed_frac * refrigerant_gwp * (-0.5)

    # embodied for outdoor unit
    embodied = system.material_weight_kg * embodied_factor

    return refrigerant_emissions + reclaimed_credit + embodied


def calc_baseline_indirect(system: SystemInputs,
                           lifetime_years: int,
                           grid_factor: float) -> float:
    cap = system.capacity_btuh
    cooling_kwh = (cap * DEFAULT_COOLING_HOURS) / (system.seer2 * 1000.0)
    heating_kwh = (cap * DEFAULT_HEATING_HOURS) / (system.hspf2 * 1000.0)

    annual_kwh = cooling_kwh + heating_kwh
    annual_kgco2 = annual_kwh * grid_factor
    return annual_kgco2 * lifetime_years


# ----------------------------
# CORRECTION FACTORS
# ----------------------------
def build_direct_cf(cf: DirectCFInputs) -> float:
    cf_val = 1.0

    # reclaimed per unit
    if cf.reclaimed_per_unit_pct >= 50:
        cf_val *= 0.9
    elif cf.reclaimed_per_unit_pct >= 20:
        cf_val *= 0.95

    # unit volume
    if cf.unit_volume_cuft <= 6:
        cf_val *= 0.97
    elif cf.unit_volume_cuft <= 10:
        cf_val *= 0.99

    # manufactured in USA
    if cf.manufactured_in_usa:
        cf_val *= 0.98

    # leak detectors
    if cf.leak_detectors:
        cf_val *= 0.95

    # refrigerant safety
    safety = cf.refrigerant_safety_class.strip().upper()
    if safety == "2L":
        cf_val *= 0.995
    elif safety == "3":
        cf_val *= 1.01

    return cf_val


def build_indirect_cf(cf: IndirectCFInputs) -> float:
    cf_val = 1.0

    ctype = cf.compressor_type.lower().strip()
    if ctype.startswith("1"):
        cf_val *= 1.00
    elif "2" in ctype:
        cf_val *= 0.95
    elif "var" in ctype:
        cf_val *= 0.90

    if cf.demand_flex:
        cf_val *= 0.97

    if cf.connected_thermostat:
        cf_val *= 0.98

    return cf_val


# ----------------------------
# STREAMLIT UI
# ----------------------------
def main():
    st.title("LCCP Interactive Model")
    st.caption("Direct + Indirect with feature-based correction factors")

    # Sidebar: global assumptions
    st.sidebar.header("Global Assumptions")
    lifetime = st.sidebar.slider("System lifetime (years)", 10, 25, DEFAULT_LIFETIME_YEARS)
    grid = st.sidebar.number_input("Grid emission factor (kgCO2/kWh)", 0.1, 1.5, DEFAULT_GRID_KGCO2_PER_KWH, 0.01)
    refrigerant_gwp = st.sidebar.number_input("Refrigerant GWP", 1.0, 4000.0, DEFAULT_REFRIG_GWP, 1.0)
    embodied_factor = st.sidebar.number_input("Embodied factor (kgCO2 per kg material)", 0.1, 20.0, EMBODIED_KGCO2_PER_KG_MATERIAL, 0.1)

    col1, col2 = st.columns(2)

    # System inputs
    with col1:
        st.subheader("System Inputs")
        cap = st.number_input("System capacity (Btuh)", 9000.0, 120000.0, 36000.0, 500.0)
        seer2 = st.number_input("SEER2", 8.0, 30.0, 15.0, 0.1)
        hspf2 = st.number_input("HSPF2", 5.0, 14.0, 8.5, 0.1)
        charge = st.number_input("Refrigerant charge (kg)", 0.5, 15.0, 3.0, 0.1)
        reclaimed_init = st.slider("Reclaimed refrigerant at initial charge (%)", 0, 100, 0)
        annual_leak = st.slider("Annual leakage rate (%)", 0, 30, 4)
        eol_loss = st.slider("End-of-life refrigerant loss (%)", 0, 100, 85)
        material_wt = st.number_input("Material weight of outdoor unit (kg)", 10.0, 350.0, 140.0, 1.0)

    # Direct CF inputs
    with col2:
        st.subheader("Direct CF Features")
        d_reclaimed = st.slider("Refrigerant reclaimed per unit (%) (field/EoL)", 0, 100, 0)
        d_volume = st.number_input("Unit volume (cu.ft)", 1.0, 80.0, 12.0, 0.5)
        d_usa = st.checkbox("Manufactured in USA?")
        d_leakdet = st.checkbox("Leak detectors present?")
        d_safety = st.selectbox("Refrigerant safety class", ["1", "2L", "2", "3"])

    # Indirect CF inputs
    st.subheader("Indirect CF Features")
    i_comp = st.selectbox("Compressor type", ["1-stg", "2-stg", "variable"])
    i_df = st.checkbox("Demand flexibility (DR) available?")
    i_ct = st.checkbox("Connected/smart thermostat?")

    # Build objects
    system = SystemInputs(
        capacity_btuh=cap,
        seer2=seer2,
        hspf2=hspf2,
        refrigerant_charge_kg=charge,
        reclaimed_refrigerant_pct=reclaimed_init,
        annual_leak_rate_pct=annual_leak,
        eol_loss_pct=eol_loss,
        material_weight_kg=material_wt,
    )

    d_cf_inputs = DirectCFInputs(
        reclaimed_per_unit_pct=d_reclaimed,
        unit_volume_cuft=d_volume,
        manufactured_in_usa=d_usa,
        leak_detectors=d_leakdet,
        refrigerant_safety_class=d_safety,
    )

    i_cf_inputs = IndirectCFInputs(
        compressor_type=i_comp,
        demand_flex=i_df,
        connected_thermostat=i_ct,
    )

    # Baselines
    base_direct = calc_baseline_direct(system,
                                       refrigerant_gwp=refrigerant_gwp,
                                       lifetime_years=lifetime,
                                       embodied_factor=embodied_factor)
    base_indirect = calc_baseline_indirect(system,
                                            lifetime_years=lifetime,
                                            grid_factor=grid)

    # CFs
    direct_cf_mult = build_direct_cf(d_cf_inputs)
    indirect_cf_mult = build_indirect_cf(i_cf_inputs)

    adj_direct = base_direct * direct_cf_mult
    adj_indirect = base_indirect * indirect_cf_mult
    total_lccp = adj_direct + adj_indirect

    st.markdown("---")
    st.subheader("Results")

    c1, c2, c3 = st.columns(3)
    c1.metric("Baseline Direct (kgCO2e)", f"{base_direct:,.0f}")
    c2.metric("Baseline Indirect (kgCO2e)", f"{base_indirect:,.0f}")
    c3.metric("Total LCCP (kgCO2e)", f"{total_lccp:,.0f}")

    st.write(f"Direct CF multiplier: **{direct_cf_mult:.3f}**")
    st.write(f"Indirect CF multiplier: **{indirect_cf_mult:.3f}**")

    # ----------------------------
    # CHART
    # ----------------------------
    st.subheader("Emission Breakdown (kgCO2e)")
    chart_df = pd.DataFrame(
        {
            "label": [
                "Baseline Direct",
                "Adjusted Direct",
                "Baseline Indirect",
                "Adjusted Indirect",
                "Total LCCP",
            ],
            "kgCO2e": [
                base_direct,
                adj_direct,
                base_indirect,
                adj_indirect,
                total_lccp,
            ],
        }
    )
    st.bar_chart(chart_df.set_index("label"))

    # ----------------------------
    # CSV EXPORT
    # ----------------------------
    st.subheader("Export Results")
    export_df = pd.DataFrame(
        {
            "metric": [
                "capacity_btuh",
                "seer2",
                "hspf2",
                "refrigerant_charge_kg",
                "baseline_direct_kgco2e",
                "adjusted_direct_kgco2e",
                "baseline_indirect_kgco2e",
                "adjusted_indirect_kgco2e",
                "total_lccp_kgco2e",
                "direct_cf_multiplier",
                "indirect_cf_multiplier",
            ],
            "value": [
                cap,
                seer2,
                hspf2,
                charge,
                base_direct,
                adj_direct,
                base_indirect,
                adj_indirect,
                total_lccp,
                direct_cf_mult,
                indirect_cf_mult,
            ],
        }
    )

    csv_bytes = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download CSV of this run",
        data=csv_bytes,
        file_name="lccp_results.csv",
        mime="text/csv",
    )

    st.markdown("---")
    st.caption("Run locally: Streamlit is free on your machine. Only the hosted service costs money.")

if __name__ == "__main__":
    main()
