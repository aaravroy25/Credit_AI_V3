import os
import re
import json
import math
import hashlib
from datetime import datetime

import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)
WORLD_BANK_BASE = "https://api.worldbank.org/v2"
REQUEST_TIMEOUT = 20

# ---------------------------------------------------------------------------
# Reference data: countries -> states/provinces -> cities, alt-data rails,
# currency info and approximate coordinates used to render the 3D globe.
# ---------------------------------------------------------------------------

COUNTRIES = {
    "India": {
        "iso3": "IND",
        "currency": "INR",
        "currencySymbol": "₹",
        "coords": [22.9734, 78.6569],
        "dataRails": ["UPI real-time payments", "Aadhaar e-KYC", "Bharat Bill Pay (BBPS)", "GST e-invoicing trail"],
        "states": {
            "Maharashtra": {"cities": {"Mumbai": {"premium": True}, "Pune": {"premium": True}, "Nagpur": {"premium": False}}},
            "Delhi NCR": {"cities": {"New Delhi": {"premium": True}, "Gurugram": {"premium": True}, "Noida": {"premium": False}}},
            "Karnataka": {"cities": {"Bengaluru": {"premium": True}, "Mysuru": {"premium": False}, "Mangaluru": {"premium": False}}},
            "Tamil Nadu": {"cities": {"Chennai": {"premium": True}, "Coimbatore": {"premium": False}, "Madurai": {"premium": False}}},
            "Gujarat": {"cities": {"Ahmedabad": {"premium": True}, "Surat": {"premium": True}, "Vadodara": {"premium": False}}},
            "West Bengal": {"cities": {"Kolkata": {"premium": True}, "Siliguri": {"premium": False}}},
        },
    },
    "Nigeria": {
        "iso3": "NGA",
        "currency": "NGN",
        "currencySymbol": "₦",
        "coords": [9.0820, 8.6753],
        "dataRails": ["Mobile money (OPay, PalmPay, Moniepoint)", "BVN e-KYC", "USSD banking logs", "Paystack/Flutterwave merchant data"],
        "states": {
            "Lagos": {"cities": {"Lagos Island": {"premium": True}, "Ikeja": {"premium": True}, "Ajah": {"premium": False}}},
            "Federal Capital Territory": {"cities": {"Abuja": {"premium": True}, "Gwagwalada": {"premium": False}}},
            "Rivers": {"cities": {"Port Harcourt": {"premium": True}, "Bonny": {"premium": False}}},
            "Kano": {"cities": {"Kano City": {"premium": False}, "Wudil": {"premium": False}}},
            "Oyo": {"cities": {"Ibadan": {"premium": False}, "Ogbomosho": {"premium": False}}},
        },
    },
    "Kenya": {
        "iso3": "KEN",
        "currency": "KES",
        "currencySymbol": "KSh",
        "coords": [-0.0236, 37.9062],
        "dataRails": ["M-Pesa mobile money", "Huduma Namba e-KYC", "Till Number merchant records", "Sacco micro-lending data"],
        "states": {
            "Nairobi County": {"cities": {"Nairobi CBD": {"premium": True}, "Westlands": {"premium": True}, "Kibera": {"premium": False}}},
            "Mombasa County": {"cities": {"Mombasa Island": {"premium": True}, "Nyali": {"premium": False}}},
            "Kisumu County": {"cities": {"Kisumu City": {"premium": False}, "Ahero": {"premium": False}}},
            "Nakuru County": {"cities": {"Nakuru Town": {"premium": False}, "Naivasha": {"premium": False}}},
        },
    },
    "Bangladesh": {
        "iso3": "BGD",
        "currency": "BDT",
        "currencySymbol": "৳",
        "coords": [23.6850, 90.3563],
        "dataRails": ["bKash / Nagad mobile wallets", "NID e-KYC", "SME cluster trade data", "Ready-made garments export ledger"],
        "states": {
            "Dhaka Division": {"cities": {"Dhaka": {"premium": True}, "Narayanganj": {"premium": True}, "Gazipur": {"premium": False}}},
            "Chattogram Division": {"cities": {"Chattogram": {"premium": True}, "Cox's Bazar": {"premium": False}}},
            "Khulna Division": {"cities": {"Khulna": {"premium": False}, "Jessore": {"premium": False}}},
            "Rajshahi Division": {"cities": {"Rajshahi": {"premium": False}, "Bogura": {"premium": False}}},
        },
    },
    "Philippines": {
        "iso3": "PHL",
        "currency": "PHP",
        "currencySymbol": "₱",
        "coords": [12.8797, 121.7740],
        "dataRails": ["GCash / Maya e-wallets", "PhilSys National ID", "QR Ph unified payments", "Sari-sari store POS ledgers"],
        "states": {
            "Metro Manila": {"cities": {"Makati": {"premium": True}, "Quezon City": {"premium": True}, "Taguig": {"premium": True}}},
            "Cebu": {"cities": {"Cebu City": {"premium": True}, "Mandaue": {"premium": False}}},
            "Davao Region": {"cities": {"Davao City": {"premium": False}, "Tagum": {"premium": False}}},
        },
    },
    "Indonesia": {
        "iso3": "IDN",
        "currency": "IDR",
        "currencySymbol": "Rp",
        "coords": [-0.7893, 113.9213],
        "dataRails": ["OVO / GoPay / DANA e-wallets", "QRIS unified QR payments", "Warung merchant ledgers", "KYC via Dukcapil"],
        "states": {
            "DKI Jakarta": {"cities": {"Central Jakarta": {"premium": True}, "South Jakarta": {"premium": True}, "North Jakarta": {"premium": False}}},
            "Bali": {"cities": {"Denpasar": {"premium": True}, "Ubud": {"premium": True}, "Singaraja": {"premium": False}}},
            "West Java": {"cities": {"Bandung": {"premium": False}, "Bekasi": {"premium": False}}},
            "East Java": {"cities": {"Surabaya": {"premium": True}, "Malang": {"premium": False}}},
        },
    },
}

INDUSTRIES = [
    "Retail & General Trade",
    "Food & Beverage",
    "Agriculture & Agri-Trade",
    "Manufacturing & Light Industry",
    "Textiles & Apparel",
    "Transportation & Logistics",
    "Construction & Building Materials",
    "Beauty & Personal Care Services",
    "Repair & Technical Services",
    "Education & Tutoring",
    "Healthcare & Pharmacy",
    "Handicrafts & Artisan Goods",
    "Digital Services & IT",
    "Hospitality & Tourism",
    "Wholesale Trade",
]

# Approximate macro fallback reference (used only if the World Bank API is
# unreachable) so the demo never breaks without connectivity.
MACRO_FALLBACK = {
    "IND": {"inflation": 5.4, "gdpGrowth": 7.0, "year": "2024"},
    "NGA": {"inflation": 22.0, "gdpGrowth": 3.1, "year": "2024"},
    "KEN": {"inflation": 6.9, "gdpGrowth": 5.0, "year": "2024"},
    "BGD": {"inflation": 9.7, "gdpGrowth": 5.8, "year": "2024"},
    "PHL": {"inflation": 3.9, "gdpGrowth": 5.7, "year": "2024"},
    "IDN": {"inflation": 2.8, "gdpGrowth": 5.0, "year": "2024"},
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# EMI maths
# ---------------------------------------------------------------------------

def compute_emi(principal, annual_rate, tenure_months):
    principal = max(0.0, float(principal))
    tenure_months = max(1, int(tenure_months))
    monthly_rate = float(annual_rate) / 12.0 / 100.0
    if monthly_rate <= 0:
        emi = principal / tenure_months
    else:
        factor = (1 + monthly_rate) ** tenure_months
        emi = principal * monthly_rate * factor / (factor - 1)
    total_payment = emi * tenure_months
    total_interest = total_payment - principal
    return {
        "emi": round(emi, 2),
        "totalPayment": round(total_payment, 2),
        "totalInterest": round(total_interest, 2),
    }


# ---------------------------------------------------------------------------
# Deterministic, transparent factor scoring (0-100 each)
# ---------------------------------------------------------------------------

def score_digital_payment_health(monthly_revenue, txn_volume, freq_per_week, weeks_inactive_6mo):
    revenue = max(1.0, float(monthly_revenue))
    volume_ratio = clamp(float(txn_volume) / revenue, 0, 1.2)
    volume_score = clamp(volume_ratio / 1.0, 0, 1) * 100

    freq_score = clamp(float(freq_per_week) / 20.0, 0, 1) * 100

    inactivity_ratio = clamp(float(weeks_inactive_6mo) / 26.0, 0, 1)
    consistency_score = (1 - inactivity_ratio) * 100

    blended = volume_score * 0.45 + freq_score * 0.30 + consistency_score * 0.25
    return round(clamp(blended, 0, 100), 1)


def score_utility_reliability(on_time_rate):
    rate = clamp(float(on_time_rate), 0, 100)
    if rate >= 70:
        return round(rate, 1)
    # Penalize sub-70% reliability more steeply (non-linear).
    penalized = rate * (rate / 70.0)
    return round(clamp(penalized, 0, 100), 1)


def score_business_stability(years_operating, employees, monthly_revenue):
    years = max(0.0, float(years_operating))
    years_score = clamp(math.log1p(years) / math.log1p(10), 0, 1) * 100

    emp = max(0, int(employees))
    emp_score = clamp(math.log1p(emp) / math.log1p(20), 0, 1) * 100

    revenue = max(0.0, float(monthly_revenue))
    revenue_score = clamp(math.log1p(revenue) / math.log1p(2_000_000), 0, 1) * 100

    blended = years_score * 0.45 + emp_score * 0.25 + revenue_score * 0.30
    return round(clamp(blended, 0, 100), 1)


def score_debt_burden(existing_emi, new_emi, monthly_revenue):
    revenue = max(1.0, float(monthly_revenue))
    dti = (float(existing_emi) + float(new_emi)) / revenue
    dti_percent = dti * 100
    score = 100 - clamp(dti_percent, 0, 100) * (100 / 60.0)
    return round(clamp(score, 0, 100), 1), round(dti_percent, 1)


# ---------------------------------------------------------------------------
# Gemini helpers (with deterministic fallbacks so the app never breaks)
# ---------------------------------------------------------------------------

def _extract_json_block(text):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        first_brace = min(
            (i for i in [text.find("{"), text.find("[")] if i != -1), default=-1
        )
        if first_brace != -1:
            text = text[first_brace:]
    return json.loads(text)


def call_gemini(prompt, system_instruction=None, temperature=0.6, max_output_tokens=768):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not configured")

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    resp = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text.strip():
        raise RuntimeError("Gemini returned empty text")
    return text


def _stable_pseudo_score(*parts, lo=40, hi=85):
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 1000 / 1000.0
    return round(lo + bucket * (hi - lo), 1)


def get_market_demand(country, state, city, industry, business_name):
    fallback_score = _stable_pseudo_score(country, state, city, industry, lo=45, hi=82)
    fallback = {
        "demandScore": fallback_score,
        "trend": "Stable",
        "reasoning": (
            f"Estimated from typical {industry.lower()} demand patterns in {city}, {state}, "
            f"{country}. Configure GEMINI_API_KEY for live AI-generated market analysis."
        ),
        "source": "fallback",
    }
    try:
        prompt = (
            "You are an economic analyst estimating LOCAL market demand for a small business "
            "as one input into an alternative credit score. Respond with ONLY compact JSON, no "
            "markdown, matching exactly this schema: "
            '{"demandScore": <integer 0-100>, "trend": "<Rising|Stable|Declining>", '
            '"reasoning": "<one or two sentence explanation, specific to the location and industry>"}. '
            f"Business: '{business_name}', Industry: {industry}. "
            f"Location: {city}, {state}, {country}. "
            "Base the score on realistic local consumer demand, competition density, and "
            "growth trends for this specific industry in this specific city."
        )
        text = call_gemini(prompt, temperature=0.5)
        parsed = _extract_json_block(text)
        score = clamp(float(parsed.get("demandScore", fallback_score)), 0, 100)
        return {
            "demandScore": round(score, 1),
            "trend": str(parsed.get("trend", "Stable"))[:20],
            "reasoning": str(parsed.get("reasoning", fallback["reasoning"]))[:400],
            "source": "gemini",
        }
    except Exception:
        return fallback


def get_ai_insights(context):
    fallback_insights = build_fallback_insights(context)
    try:
        prompt = (
            "You are a credit analyst assistant for CreditLens, an alternative credit scoring "
            "platform for small businesses in emerging markets. Given the computed factor scores "
            "below (each 0-100, higher is better), write 4 to 6 short, specific, actionable insight "
            "strings for the business owner. Mention concrete strengths and concrete areas to "
            "improve, referencing the actual numbers where useful. Respond with ONLY a compact "
            'JSON array of strings, e.g. ["insight one", "insight two", ...]. No markdown fences.\n\n'
            f"Business: {context['businessName']} ({context['industry']}) in {context['city']}, "
            f"{context['state']}, {context['country']}.\n"
            f"Final Alt-Credit Score: {context['score']} / 900 (tier: {context['tier']}).\n"
            f"Digital Payment Health: {context['digital']}/100 (weight 35%)\n"
            f"Utility Bill Reliability: {context['utility']}/100 (weight 15%)\n"
            f"Business Stability: {context['stability']}/100 (weight 15%)\n"
            f"Debt Burden: {context['debt']}/100, debt-to-income {context['dti']}% (weight 15%)\n"
            f"Local Market Demand: {context['demand']}/100 (weight 12%)\n"
            f"Macroeconomic Context: {context['macro']}/100 (weight 8%)\n"
        )
        text = call_gemini(prompt, temperature=0.6, max_output_tokens=512)
        parsed = _extract_json_block(text)
        if isinstance(parsed, list) and parsed:
            return [str(x)[:220] for x in parsed][:6]
        return fallback_insights
    except Exception:
        return fallback_insights


def build_fallback_insights(context):
    insights = []
    factor_labels = {
        "digital": "Digital Payment Health",
        "utility": "Utility Bill Reliability",
        "stability": "Business Stability",
        "debt": "Debt Burden",
        "demand": "Local Market Demand",
        "macro": "Macroeconomic Context",
    }
    scored = {k: context[k] for k in factor_labels}
    best_key = max(scored, key=scored.get)
    worst_key = min(scored, key=scored.get)
    insights.append(
        f"Your strongest factor is {factor_labels[best_key]} at {scored[best_key]}/100 — "
        "lenders will view this favorably."
    )
    insights.append(
        f"{factor_labels[worst_key]} at {scored[worst_key]}/100 is your biggest opportunity to "
        "improve your score."
    )
    if context["dti"] > 45:
        insights.append(
            f"Your debt-to-income ratio is {context['dti']}%, above the recommended 45% threshold. "
            "Consider a smaller loan amount or longer tenure."
        )
    else:
        insights.append(
            f"Your debt-to-income ratio of {context['dti']}% is within a healthy range for new credit."
        )
    insights.append(
        f"Increasing consistent digital transaction volume in {context['city']} can meaningfully "
        "lift your Digital Payment Health score, the highest-weighted factor at 35%."
    )
    insights.append(
        f"Maintaining on-time utility payments strengthens the Utility Bill Reliability factor, "
        "a low-effort way to build score history."
    )
    return insights[:5]


def chat_with_gemini(message, history):
    system_instruction = (
        "You are the CreditLens Assistant, a friendly, concise in-app chatbot for CreditLens — "
        "an AI-powered alternative credit-scoring web app that helps small businesses in "
        "emerging markets (India, Nigeria, Kenya, Bangladesh, the Philippines, Indonesia) become "
        "bankable using alternative data (digital payments, utility bill reliability, business "
        "stability, debt burden, local market demand via AI, and macroeconomic context) instead "
        "of traditional credit bureau history. You help users navigate the 4-step wizard "
        "(Location -> Business Profile -> Debt & Loan Planning -> Score Dashboard) and give "
        "practical small-business financial advice. Keep answers short (2-5 sentences), warm, "
        "and actionable. If asked something unrelated to CreditLens or small business finance, "
        "gently redirect."
    )
    if not GEMINI_API_KEY:
        return fallback_chat_reply(message)
    try:
        convo = "\n".join(
            f"{'User' if h.get('role') == 'user' else 'Assistant'}: {h.get('text', '')}"
            for h in history[-8:]
        )
        prompt = f"{convo}\nUser: {message}\nAssistant:" if convo else f"User: {message}\nAssistant:"
        text = call_gemini(prompt, system_instruction=system_instruction, temperature=0.7, max_output_tokens=400)
        return text.strip()
    except Exception:
        return fallback_chat_reply(message)


def fallback_chat_reply(message):
    m = message.lower()
    if any(k in m for k in ["score", "credit", "calculate"]):
        return (
            "Your Alt-Credit Score (300-900) blends Digital Payment Health (35%), Utility Bill "
            "Reliability (15%), Business Stability (15%), Debt Burden (15%), AI-estimated Local "
            "Market Demand (12%), and Macroeconomic Context (8%). Complete the 4-step wizard to "
            "see your live breakdown!"
        )
    if any(k in m for k in ["emi", "loan", "debt", "interest"]):
        return (
            "In Step 3 you can enter your existing EMI plus a new loan amount, interest rate, and "
            "tenure — CreditLens instantly computes your monthly EMI, total interest, and "
            "debt-to-income ratio, with a warning if it exceeds the healthy 45% threshold."
        )
    if any(k in m for k in ["country", "location", "state", "city", "map"]):
        return (
            "CreditLens currently supports India, Nigeria, Kenya, Bangladesh, the Philippines, and "
            "Indonesia. Pick your country on the 3D globe in Step 1 to see the local alternative "
            "data rails we use, like UPI or M-Pesa."
        )
    if any(k in m for k in ["hi", "hello", "hey"]):
        return "Hi! I'm the CreditLens Assistant. Ask me about the scoring model, the wizard steps, or small-business finance tips."
    return (
        "I'm the CreditLens Assistant — I can help explain the Alt-Credit Score, the wizard "
        "steps, EMI calculations, or give small-business finance tips. What would you like to know?"
    )


# ---------------------------------------------------------------------------
# World Bank macroeconomic context
# ---------------------------------------------------------------------------

def _fetch_wb_indicator(iso3, indicator_code):
    url = f"{WORLD_BANK_BASE}/country/{iso3}/indicator/{indicator_code}"
    resp = requests.get(
        url,
        params={"format": "json", "per_page": 10, "mrnev": 1},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        raise RuntimeError("No data from World Bank")
    for entry in payload[1]:
        if entry.get("value") is not None:
            return float(entry["value"]), entry.get("date")
    raise RuntimeError("No non-null World Bank value")


def get_macro_context(iso3):
    try:
        inflation, inf_year = _fetch_wb_indicator(iso3, "FP.CPI.TOTL.ZG")
        gdp_growth, gdp_year = _fetch_wb_indicator(iso3, "NY.GDP.MKTP.KD.ZG")
        year = inf_year or gdp_year
        source = "worldbank"
    except Exception:
        fallback = MACRO_FALLBACK.get(iso3, {"inflation": 6.0, "gdpGrowth": 4.0, "year": "n/a"})
        inflation, gdp_growth, year = fallback["inflation"], fallback["gdpGrowth"], fallback["year"]
        source = "fallback"

    inflation_score = clamp(100 - clamp(inflation, 0, 30) / 30 * 100, 0, 100)
    gdp_score = clamp((gdp_growth + 2) / 10 * 100, 0, 100)
    macro_score = round(inflation_score * 0.5 + gdp_score * 0.5, 1)

    return {
        "inflation": round(inflation, 2),
        "gdpGrowth": round(gdp_growth, 2),
        "asOfYear": year,
        "score": macro_score,
        "source": source,
    }


TIERS = [
    (750, "Excellent", "#22d3a8", "Priority eligibility for the widest range of lenders and lowest rates."),
    (650, "Good", "#38bdf8", "Solid eligibility for most alternative-data lenders."),
    (550, "Fair", "#f5b942", "Eligible for entry-tier alternative credit products; room to grow."),
    (0, "Needs Improvement", "#f5636b", "Build more digital and utility payment history to unlock better offers."),
]


def get_tier(score):
    for threshold, label, color, note in TIERS:
        if score >= threshold:
            return {"label": label, "color": color, "note": note}
    return {"label": "Needs Improvement", "color": "#f5636b", "note": TIERS[-1][3]}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/locations")
def api_locations():
    return jsonify(COUNTRIES)


@app.route("/api/industries")
def api_industries():
    return jsonify(INDUSTRIES)


@app.route("/api/score", methods=["POST"])
def api_score():
    body = request.get_json(force=True, silent=True) or {}

    location = body.get("location", {})
    business = body.get("business", {})
    debt = body.get("debt", {})

    country = location.get("country", "India")
    state = location.get("state", "")
    city = location.get("city", "")
    country_info = COUNTRIES.get(country, COUNTRIES["India"])

    try:
        monthly_revenue = float(business.get("monthlyRevenue", 0))
        years_operating = float(business.get("yearsOperating", 0))
        employees = int(business.get("employees", 0))
        txn_volume = float(business.get("monthlyDigitalTxnVolume", 0))
        freq_per_week = float(business.get("digitalPaymentFrequencyPerWeek", 0))
        weeks_inactive = float(business.get("weeksNoDigitalActivity6mo", 0))
        utility_rate = float(business.get("utilityOnTimeRate", 0))
        industry = business.get("industry", INDUSTRIES[0])
        business_name = business.get("businessName", "Your business")

        existing_emi = float(debt.get("existingEmi", 0))
        new_loan_amount = float(debt.get("newLoanAmount", 0))
        annual_rate = float(debt.get("annualInterestRate", 0))
        tenure_months = int(debt.get("tenureMonths", 12))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid numeric input"}), 400

    emi_calc = compute_emi(new_loan_amount, annual_rate, tenure_months)

    digital_score = score_digital_payment_health(monthly_revenue, txn_volume, freq_per_week, weeks_inactive)
    utility_score = score_utility_reliability(utility_rate)
    stability_score = score_business_stability(years_operating, employees, monthly_revenue)
    debt_score, dti_percent = score_debt_burden(existing_emi, emi_calc["emi"], monthly_revenue)

    demand = get_market_demand(country, state, city, industry, business_name)
    macro = get_macro_context(country_info["iso3"])

    composite = (
        digital_score * 0.35
        + utility_score * 0.15
        + stability_score * 0.15
        + debt_score * 0.15
        + demand["demandScore"] * 0.12
        + macro["score"] * 0.08
    )
    composite = round(clamp(composite, 0, 100), 2)
    final_score = round(300 + composite / 100 * 600)
    tier = get_tier(final_score)

    insight_context = {
        "businessName": business_name,
        "industry": industry,
        "city": city,
        "state": state,
        "country": country,
        "score": final_score,
        "tier": tier["label"],
        "digital": digital_score,
        "utility": utility_score,
        "stability": stability_score,
        "debt": debt_score,
        "dti": dti_percent,
        "demand": demand["demandScore"],
        "macro": macro["score"],
    }
    ai_insights = get_ai_insights(insight_context)

    factors = [
        {
            "key": "digitalPayment",
            "label": "Digital Payment Health",
            "weight": 35,
            "rawScore": digital_score,
            "weightedContribution": round(digital_score * 0.35, 1),
            "detail": f"Digital txn volume vs revenue, {freq_per_week:.0f}x/week frequency, {weeks_inactive:.0f} inactive weeks in 6mo.",
        },
        {
            "key": "utilityReliability",
            "label": "Utility Bill Reliability",
            "weight": 15,
            "rawScore": utility_score,
            "weightedContribution": round(utility_score * 0.15, 1),
            "detail": f"{utility_rate:.0f}% of utility bills paid on time.",
        },
        {
            "key": "businessStability",
            "label": "Business Stability",
            "weight": 15,
            "rawScore": stability_score,
            "weightedContribution": round(stability_score * 0.15, 1),
            "detail": f"{years_operating:.1f} years operating, {employees} employees, {country_info['currencySymbol']}{monthly_revenue:,.0f}/mo revenue.",
        },
        {
            "key": "debtBurden",
            "label": "Debt Burden",
            "weight": 15,
            "rawScore": debt_score,
            "weightedContribution": round(debt_score * 0.15, 1),
            "detail": f"Debt-to-income at {dti_percent:.1f}% including the new loan's EMI.",
        },
        {
            "key": "marketDemand",
            "label": "Local Market Demand",
            "weight": 12,
            "rawScore": demand["demandScore"],
            "weightedContribution": round(demand["demandScore"] * 0.12, 1),
            "detail": demand["reasoning"],
        },
        {
            "key": "macroContext",
            "label": "Macroeconomic Context",
            "weight": 8,
            "rawScore": macro["score"],
            "weightedContribution": round(macro["score"] * 0.08, 1),
            "detail": f"Inflation {macro['inflation']}%, GDP growth {macro['gdpGrowth']}% ({macro['asOfYear']}).",
        },
    ]

    return jsonify(
        {
            "score": final_score,
            "scoreOutOf": 900,
            "scoreMin": 300,
            "compositeOutOf100": composite,
            "tier": tier,
            "factors": factors,
            "emi": {
                "newLoanEmi": emi_calc["emi"],
                "totalInterest": emi_calc["totalInterest"],
                "totalPayment": emi_calc["totalPayment"],
                "existingEmi": existing_emi,
                "combinedMonthlyDebt": round(existing_emi + emi_calc["emi"], 2),
                "debtToIncomePercent": dti_percent,
                "warning": dti_percent > 45,
            },
            "marketDemand": demand,
            "macro": macro,
            "aiInsights": ai_insights,
            "currency": {"code": country_info["currency"], "symbol": country_info["currencySymbol"]},
            "locationRails": country_info["dataRails"],
            "generatedAt": datetime.utcnow().isoformat() + "Z",
        }
    )


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(force=True, silent=True) or {}
    message = str(body.get("message", "")).strip()
    history = body.get("history", [])
    if not message:
        return jsonify({"error": "Message is required"}), 400
    reply = chat_with_gemini(message, history if isinstance(history, list) else [])
    return jsonify({"reply": reply, "aiPowered": bool(GEMINI_API_KEY)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
