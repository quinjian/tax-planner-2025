import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- PAGE CONFIGURATION ---
###st.set_page_config(page_title="Universal US Tax & Strategy Planner 2025", layout="wide", initial_sidebar_state="expanded")
# --- SEO CONFIGURATION ---
st.set_page_config(
    page_title="US Tax Planner & Capital Gains Calculator | Free Tool",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://www.capicomm.com/help',
        'Report a bug': "https://www.capicomm.com/bug",
        'About': "# US Tax Strategist\nThis tool helps calculate **Capital Gains**, **Roth Conversions**, and **State Taxes**."
    }
)
# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

# --- 2025 TAX CONSTANTS ---
TAX_BRACKETS = {
    'Single': [(11925, 0.10), (48475, 0.12), (103350, 0.22), (197300, 0.24), (250525, 0.32), (626350, 0.35), (float('inf'), 0.37)],
    'Married Joint': [(23850, 0.10), (96950, 0.12), (206700, 0.22), (394600, 0.24), (501050, 0.32), (751600, 0.35), (float('inf'), 0.37)]
}
LTCG_BRACKETS = {
    'Single': [(48350, 0.0), (533400, 0.15), (float('inf'), 0.20)],
    'Married Joint': [(96700, 0.0), (600050, 0.15), (float('inf'), 0.20)]
}
STD_DEDUCTION = {'Single': 15000, 'Married Joint': 30000}
SENIOR_BOOST = {'Single': 1950, 'Married Joint': 1550} # Addl deduction if 65+
HSA_LIMIT = {'Single': 4300, 'Family': 8550}
NIIT_THRESH = {'Single': 200000, 'Married Joint': 250000}
MED_THRESH = {'Single': 200000, 'Married Joint': 250000}
EV_CAP = {'Single': 150000, 'Married Joint': 300000}
SALT_CAP = 10000

# --- CONSTANTS: STATE ---
STATE_DATA = {
    "Texas (0%)": {"type": "none"},
    "Florida (0%)": {"type": "none"},
    "Washington (0%*)": {"type": "none"},
    "California (High)": {
        "type": "progressive",
        "brackets_single": [(11459, 0.01), (27169, 0.02), (42879, 0.04), (59528, 0.06), (75225, 0.08), (384534, 0.093), (461426, 0.103), (769062, 0.113), (1000000, 0.123), (float('inf'), 0.144)],
        "brackets_joint": [(22918, 0.01), (54338, 0.02), (85758, 0.04), (119056, 0.06), (150450, 0.08), (769068, 0.093), (922852, 0.103), (1538124, 0.113), (2000000, 0.123), (float('inf'), 0.144)]
    },
    "New York (High)": {
        "type": "progressive",
        "brackets_single": [(8500, 0.04), (11700, 0.045), (13900, 0.0525), (80650, 0.055), (215400, 0.06), (1077550, 0.0685), (5000000, 0.0965), (25000000, 0.103), (float('inf'), 0.109)],
        "brackets_joint": [(17150, 0.04), (23600, 0.045), (27900, 0.0525), (161550, 0.055), (323200, 0.06), (2155350, 0.0685), (5000000, 0.0965), (float('inf'), 0.109)]
    },
    "Custom / Other": {"type": "flat_input"}
}

# --- LOGIC ENGINE ---
def calculate_state_tax(taxable_income_federal, status, state_selection, custom_rate=0):
    if state_selection not in STATE_DATA: return 0
    state_info = STATE_DATA[state_selection]
    
    if state_info["type"] == "none": return 0
    elif state_info["type"] == "flat_input": return taxable_income_federal * (custom_rate / 100.0)
    elif state_info["type"] == "progressive":
        brackets = state_info["brackets_joint"] if status == 'Married Joint' else state_info["brackets_single"]
        tax = 0
        prev = 0
        for limit, rate in brackets:
            if taxable_income_federal > prev:
                amt = min(taxable_income_federal, limit) - prev
                tax += amt * rate
                prev = limit
            else: break
        return tax
    return 0

def net_schedule_d(st_stock, lt_stock, futures_1256):
    """Trader Logic: Splits Futures 60/40 and nets against stock P/L"""
    f_lt = futures_1256 * 0.60
    f_st = futures_1256 * 0.40
    
    tot_st = st_stock + f_st
    tot_lt = lt_stock + f_lt
    
    final_st, final_lt, deduct = 0, 0, 0
    
    if tot_st >= 0 and tot_lt >= 0:
        final_st, final_lt = tot_st, tot_lt
    elif tot_st < 0 and tot_lt < 0:
        deduct = min(3000, abs(tot_st + tot_lt))
    elif tot_st < 0 < tot_lt:
        net = tot_lt + tot_st
        if net >= 0: final_lt = net
        else: deduct = min(3000, abs(net))
    elif tot_lt < 0 < tot_st:
        net = tot_st + tot_lt
        if net >= 0: final_st = net
        else: deduct = min(3000, abs(net))
        
    return final_st, final_lt, deduct, (f_st, f_lt)

def calculate_tax_liability(w2_income, ltcg_income, status, deductions, credits):
    """
    Comprehensive engine handling Ordinary, LTCG, NIIT, and Medicare taxes.
    """
    # 1. Determine Taxable Ordinary Income
    effective_deduction = max(STD_DEDUCTION[status], deductions)
    taxable_ordinary = max(0, w2_income - effective_deduction)
    
    # 2. Ordinary Income Tax
    ord_tax = 0
    prev_lim = 0
    for limit, rate in TAX_BRACKETS[status]:
        if taxable_ordinary > prev_lim:
            amt = min(taxable_ordinary, limit) - prev_lim
            ord_tax += amt * rate
            prev_lim = limit
        else:
            break
            
    # 3. LTCG Tax (Stacked Method)
    current_stack = taxable_ordinary
    remaining_ltcg = ltcg_income
    ltcg_tax = 0
    
    for limit, rate in LTCG_BRACKETS[status]:
        if current_stack < limit:
            space = limit - current_stack
            taxable_amt = min(remaining_ltcg, space)
            ltcg_tax += taxable_amt * rate
            current_stack += taxable_amt
            remaining_ltcg -= taxable_amt
            
    # 4. Surtaxes
    magi = w2_income + ltcg_income
    excess_magi_niit = max(0, magi - NIIT_THRESH[status])
    niit_tax = min(ltcg_income, excess_magi_niit) * 0.038
    med_tax = max(0, w2_income - MED_THRESH[status]) * 0.009
    
    total_tax_before_credits = ord_tax + ltcg_tax + niit_tax + med_tax
    final_tax = max(0, total_tax_before_credits - credits)
    
    # Marginal Rate Calculation
    marginal_rate = 0
    for limit, rate in TAX_BRACKETS[status]:
        if taxable_ordinary < limit:
            marginal_rate = rate
            break
        elif limit == float('inf'):
            marginal_rate = rate

    return {
        "Ordinary Tax": ord_tax,
        "LTCG Tax": ltcg_tax,
        "NIIT": niit_tax,
        "Medicare": med_tax,
        "Total Liability": final_tax,
        "Marginal Rate": marginal_rate,
        "Effective Rate": final_tax / magi if magi > 0 else 0,
        "Taxable Ordinary": taxable_ordinary
    }

def project_investment_growth(principal, annual_contrib, years, growth_rate=0.08):
    """Generates year-by-year growth data."""
    balance = []
    years_list = list(range(years + 1))
    curr = principal
    for _ in range(years):
        balance.append(curr)
        curr = curr * (1 + growth_rate) + annual_contrib
    balance.append(curr)
    return years_list, balance

# --- SIDEBAR NAVIGATION ---
st.sidebar.title("🇺🇸 Tax Strategist")
app_mode = st.sidebar.radio("Select Planner Mode:", ["Standard Planner", "Advanced / HNWI"], help="Standard: For general retirement & W2 planning.\nAdvanced: For complex income, capital gains, & surtaxes.")

# --- SHARED INPUTS ---
st.sidebar.subheader("1. Profile")
filing_status = st.sidebar.selectbox("Filing Status", ["Single", "Married Joint"])
current_age = st.sidebar.number_input("Current Age", 30, 80, 35)

if app_mode == "Standard Planner":
    # === STANDARD MODE UI ===
    st.title("Retirement & Tax Optimization Planner")

    # --- MOBILE FRIENDLY INPUTS ---
    # On mobile, the sidebar is hidden. This puts key inputs front-and-center.
    with st.expander("📱 Tap here to Edit Income & Settings", expanded=False):
        st.write("For full settings, open the sidebar menu (top-left).")
        # We duplicate the most important input here for convenience
        mobile_w2 = st.number_input("Quick Update: W2 Income", value=120000, step=5000, key="mobile_w2_input")
    
        # If the user types here, we overwrite the sidebar value logic
        if mobile_w2 != 120000:
            w2_input = mobile_w2
            # Note: To make this fully sync 2-ways is complex in Streamlit, 
            # but this simple version works for quick "What-Ifs" on a phone.
    
    # Inputs
    col1, col2, col3 = st.columns(3)
    with col1:
        gross_income = st.number_input("Gross Annual Income ($)", value=120000, step=5000)
    with col2:
        retirement_age = st.number_input("Target Retirement Age", value=65)
    with col3:
        hsa_eligible = st.checkbox("HSA Eligible (HDHP)?", value=True)
    
    ###ev_purchase = st.selectbox("Buying an EV in 2025?", ["No", "Yes (Before Sept 30)", "Yes (After Sept 30)"])
    ev_purchase = st.number_input("Other Credit such as Buying an EV in 2025?", value=7500)
    invest_budget = st.slider("Annual Investment Budget ($)", 0, 50000, 15000)

    # Logic
    hsa_deduction = 0
    if hsa_eligible:
        hsa_deduction = HSA_LIMIT['Family'] if filing_status == 'Married Joint' else HSA_LIMIT['Single']

    ev_credit = ev_purchase
    ev_msg = ""
    # if ev_purchase != "No":
    #     cap = EV_CAP[filing_status]
    #     if gross_income > cap:
    #         ev_msg = "❌ Income exceeds cap."
    #     elif "After" in ev_purchase:
    #         ev_msg = "⚠️ Uncertain (Rules change Oct 1)."
    #     else:
    #         ev_credit = 7500
    #         ev_msg = "✅ $7,500 Credit."

    # Advanced Inputs
    with st.sidebar:
        st.divider()
        # st.subheader("2. Income Details")
        # w2_input = st.number_input("W2 / Business Income", value=450000, step=10000)
        # ltcg_input = st.number_input("Capital Gains / Divs", value=100000, step=5000)
        
        # st.subheader("3. Strategy Marketplace")
        # strat_tlh = st.checkbox("Tax-Loss Harvesting")
        # tlh_val = st.slider("Harvested Losses ($)", 0, 50000, 10000) if strat_tlh else 0
        
        # strat_charity = st.checkbox("Charitable Giving (DAF)")
        # charity_val = st.number_input("Donation Amount ($)", value=25000) if strat_charity else 0
        
        # strat_401k = st.checkbox("Max 401k/SEP Deferral")
        # def_val = 23500 if strat_401k else 0

        ###st.divider() # Adds a visual line separator
        st.markdown("### ☕ Support the Dev")
        st.write("Did this tool help you with valuable information? Your support helps keep it free and updated!")
    
        # Replace 'YOUR_USERNAME' with your actual Buy Me a Coffee username
        bmc_link = "https://www.buymeacoffee.com/ujqui"
    
        st.markdown(
            f"""
            <a href="{bmc_link}" target="_blank">
            <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 180px !important;" >
            </a>
            """,
            unsafe_allow_html=True
        )
    
        st.caption("All tips count as 'Business Income' for development services.")
    
    # Calculation
    results = calculate_tax_liability(gross_income, 0, filing_status, hsa_deduction, ev_credit)

    # Strategy: Trad vs Roth
    years = retirement_age - current_age
    marg_rate = results['Marginal Rate']
    
    x, y_trad = project_investment_growth(0, invest_budget, years)
    final_trad = y_trad[-1] * 0.80 # Assume 20% tax on withdrawal
    
    tax_hit = invest_budget * marg_rate
    roth_contrib = invest_budget - tax_hit
    x, y_roth = project_investment_growth(0, roth_contrib, years)
    final_roth = y_roth[-1]

    # Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Est. Tax Bill", f"${results['Total Liability']:,.0f}")
    m2.metric("Marginal Rate", f"{results['Marginal Rate']:.0%}")
    m3.metric("Effective Rate", f"{results['Effective Rate']:.1%}")
    m4.metric("EV Credit", f"${ev_credit}", delta=ev_msg)

    # Charts
    tab1, tab2 = st.tabs(["📈 Wealth Projection", "📋 Recommendations"])
    with tab1:
        st.subheader(f"Traditional vs. Roth Analysis ({years} Year Horizon)")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=y_trad, name="Traditional (Pre-Tax Balance)", line=dict(color='blue')))
        fig.add_trace(go.Scatter(x=x, y=y_roth, name="Roth (Post-Tax Balance)", line=dict(color='green')))
        st.plotly_chart(fig, use_container_width=True)
        
    with tab2:
        st.subheader("Action Plan")
        st.markdown(f"""
        1. **HSA:** {"Maximize your HSA contribution of $" + str(hsa_deduction) + "." if hsa_eligible else "Not applicable."}
        2. **Retirement Account:** Based on your {marg_rate:.0%} bracket, prioritize **{"Traditional 401k/IRA" if marg_rate >= 0.22 else "Roth IRA/401k"}**.
        """)

else:
    # === ADVANCED / HNWI MODE UI ===
    st.title("Advanced Tax Strategy & Simulation")

    # # --- MOBILE FRIENDLY INPUTS ---
    # # On mobile, the sidebar is hidden. This puts key inputs front-and-center.
    # with st.expander("📱 Tap here to Edit Income & Settings", expanded=False):
    #     st.write("For full settings, open the sidebar menu (top-left).")
    #     # We duplicate the most important input here for convenience
    #     mobile_w2 = st.number_input("Quick Update: W2 Income", value=w2_in, step=5000, key="mobile_w2_input")
    
    #     # If the user types here, we overwrite the sidebar value logic
    #     if mobile_w2 != w2_in:
    #         w2_in = mobile_w2
    #         # Note: To make this fully sync 2-ways is complex in Streamlit, 
    #         # but this simple version works for quick "What-Ifs" on a phone.

    # Advanced Inputs
    with st.sidebar:
        st.divider()
        st.subheader("2. Income Details")
        w2_input = st.number_input("W2 / Business Income", value=450000, step=10000)
        ltcg_input = st.number_input("Capital Gains / Divs", value=100000, step=5000)
        
        st.subheader("3. Strategy Marketplace")
        strat_tlh = st.checkbox("Tax-Loss Harvesting")
        tlh_val = st.slider("Harvested Losses ($)", 0, 50000, 10000) if strat_tlh else 0
        
        strat_charity = st.checkbox("Charitable Giving (DAF)")
        charity_val = st.number_input("Donation Amount ($)", value=25000) if strat_charity else 0
        
        strat_401k = st.checkbox("Max 401k/SEP Deferral")
        def_val = 23500 if strat_401k else 0

        ###st.divider() # Adds a visual line separator
        st.markdown("### ☕ Support the Dev")
        st.write("Did this tool help you with valuable information? Your support helps keep it free and updated!")
    
        # Replace 'YOUR_USERNAME' with your actual Buy Me a Coffee username
        bmc_link = "https://www.buymeacoffee.com/ujqui"
    
        st.markdown(
            f"""
            <a href="{bmc_link}" target="_blank">
            <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 180px !important;" >
            </a>
            """,
            unsafe_allow_html=True
        )
    
        st.caption("All tips count as 'Business Income' for development services.")

    # 1. Baseline Calculation
    base_res = calculate_tax_liability(w2_input, ltcg_input, filing_status, 0, 0)
    
    # 2. Optimized Calculation
    applied_ltcg_deduct = min(ltcg_input, tlh_val)
    remaining_loss = tlh_val - applied_ltcg_deduct
    applied_ord_deduct = min(3000, remaining_loss) + charity_val + def_val
    opt_ltcg_income = max(0, ltcg_input - applied_ltcg_deduct)
    
    opt_res = calculate_tax_liability(w2_input, opt_ltcg_income, filing_status, applied_ord_deduct, 0)
    savings = base_res['Total Liability'] - opt_res['Total Liability']
    
    # Dashboard
    c1, c2, c3 = st.columns(3)
    c1.metric("Current Liability", f"${base_res['Total Liability']:,.0f}")
    c2.metric("Optimized Liability", f"${opt_res['Total Liability']:,.0f}", delta=f"-${savings:,.0f}", delta_color="inverse")
    c3.metric("Net Investment Tax (NIIT)", f"${opt_res['NIIT']:,.0f}", help="3.8% Surtax")
    
    # Visualization Tabs
    t1, t2 = st.tabs(["📊 Savings Waterfall", "📝 Detailed Ledger"])
    
    with t1:
        fig = go.Figure(go.Waterfall(
            name = "Tax", orientation = "v",
            measure = ["relative", "relative", "relative", "total"],
            x = ["Baseline Tax", "Strategies Applied", "Surtax Reduction", "Final Bill"],
            textposition = "outside",
            text = [f"${base_res['Total Liability']/1000:.0f}k", f"-${(base_res['Ordinary Tax']-opt_res['Ordinary Tax'] + base_res['LTCG Tax']-opt_res['LTCG Tax'])/1000:.1f}k", "...", f"${opt_res['Total Liability']/1000:.0f}k"],
            y = [
                base_res['Total Liability'],
                -(base_res['Ordinary Tax'] - opt_res['Ordinary Tax'] + base_res['LTCG Tax'] - opt_res['LTCG Tax']),
                -(base_res['NIIT'] - opt_res['NIIT']),
                opt_res['Total Liability']
            ],
            connector = {"line":{"color":"rgb(63, 63, 63)"}},
        ))
        st.plotly_chart(fig, use_container_width=True)

    with t2:
        # Dataframe creation
        df_data = {
            "Item": ["Ordinary Income", "LTCG Income", "Taxable Ordinary", "Ordinary Tax", "LTCG Tax", "NIIT (3.8%)", "Medicare (0.9%)", "TOTAL TAX"],
            "Baseline": [
                w2_input, ltcg_input, base_res['Taxable Ordinary'], base_res['Ordinary Tax'], 
                base_res['LTCG Tax'], base_res['NIIT'], base_res['Medicare'], base_res['Total Liability']
            ],
            "Optimized": [
                w2_input - applied_ord_deduct, opt_ltcg_income, opt_res['Taxable Ordinary'], opt_res['Ordinary Tax'],
                opt_res['LTCG Tax'], opt_res['NIIT'], opt_res['Medicare'], opt_res['Total Liability']
            ]
        }
        df = pd.DataFrame(df_data)
        df['Savings'] = df['Baseline'] - df['Optimized']
        
        # --- FIX: Apply format ONLY to numeric columns ---
        # "Item" column is ignored by the formatter to prevent the ValueError
        st.dataframe(
            df.style.format(
                subset=["Baseline", "Optimized", "Savings"], 
                formatter="${:,.0f}"
            ), 
            use_container_width=True
        )