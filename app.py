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

def _build_countries(raw):
    countries = {}
    for name, iso2, iso3, currency, symbol, lat, lng, rails, states in raw:
        state_dict = {}
        for state_name, cities in states:
            state_dict[state_name] = {"cities": {c: {"premium": p} for c, p in cities}}
        countries[name] = {
            "iso2": iso2,
            "iso3": iso3,
            "currency": currency,
            "currencySymbol": symbol,
            "coords": [lat, lng],
            "dataRails": list(rails),
            "states": state_dict,
        }
    return countries


# Each entry: (name, iso2, iso3, currency, symbol, lat, lng, dataRails, states)
# states: tuple of (state_name, cities) where cities is a tuple of (city_name, is_premium)
_RAW_COUNTRIES = [
    # ---------------------------------------------------------------- Africa
    ("Algeria", "DZ", "DZA", "DZD", "DA", 36.7538, 3.0588,
        ("Mobile banking apps", "Edahabia card payments", "National ID e-KYC"),
        (("Algiers Region", (("Algiers", True), ("Oran", False))),)),
    ("Angola", "AO", "AGO", "AOA", "Kz", -8.8399, 13.2894,
        ("Multicaixa Express mobile payments", "Mobile money agents", "National ID e-KYC"),
        (("Luanda Province", (("Luanda", True), ("Huambo", False))),)),
    ("Benin", "BJ", "BEN", "XOF", "CFA", 6.4969, 2.6289,
        ("Mobile money (MTN/Moov)", "UEMOA digital payment rails", "National ID e-KYC"),
        (("Littoral", (("Cotonou", True), ("Porto-Novo", False))),)),
    ("Botswana", "BW", "BWA", "BWP", "P", -24.6282, 25.9231,
        ("Mobile money (Orange Money/MyZaka)", "National ID e-KYC", "POS digital payments"),
        (("South-East District", (("Gaborone", True), ("Francistown", False))),)),
    ("Burkina Faso", "BF", "BFA", "XOF", "CFA", 12.3714, -1.5197,
        ("Mobile money (Orange/Moov)", "UEMOA digital rails", "National ID e-KYC"),
        (("Centre Region", (("Ouagadougou", True), ("Bobo-Dioulasso", False))),)),
    ("Burundi", "BI", "BDI", "BIF", "FBu", -3.3822, 29.3644,
        ("Mobile money (Lumicash/EcoCash)", "National ID e-KYC", "Microfinance ledgers"),
        (("Bujumbura Province", (("Bujumbura", True), ("Gitega", False))),)),
    ("Cabo Verde", "CV", "CPV", "CVE", "$", 14.9330, -23.5133,
        ("Vinti4 card payments", "Mobile banking", "National ID e-KYC"),
        (("Santiago Island", (("Praia", True),)),)),
    ("Cameroon", "CM", "CMR", "XAF", "FCFA", 3.8480, 11.5021,
        ("Mobile money (MTN/Orange)", "CEMAC digital rails", "National ID e-KYC"),
        (("Centre Region", (("Yaoundé", True),)), ("Littoral", (("Douala", True),)))),
    ("Central African Republic", "CF", "CAF", "XAF", "FCFA", 4.3947, 18.5582,
        ("Mobile money agents", "National ID e-KYC", "Microfinance ledgers"),
        (("Bangui", (("Bangui", True),)),)),
    ("Chad", "TD", "TCD", "XAF", "FCFA", 12.1348, 15.0557,
        ("Mobile money (Airtel/Moov)", "National ID e-KYC", "Microfinance ledgers"),
        (("N'Djamena Region", (("N'Djamena", True),)),)),
    ("Comoros", "KM", "COM", "KMF", "CF", -11.7042, 43.2402,
        ("Mobile money agents", "National ID e-KYC"),
        (("Grande Comore", (("Moroni", True),)),)),
    ("Congo (Republic of)", "CG", "COG", "XAF", "FCFA", -4.2634, 15.2429,
        ("Mobile money (MTN/Airtel)", "National ID e-KYC"),
        (("Brazzaville", (("Brazzaville", True),)),)),
    ("Congo (DR)", "CD", "COD", "CDF", "FC", -4.4419, 15.2663,
        ("Mobile money (Orange/Airtel/M-Pesa)", "National ID e-KYC", "Microfinance ledgers"),
        (("Kinshasa", (("Kinshasa", True),)), ("Haut-Katanga", (("Lubumbashi", True),)))),
    ("Djibouti", "DJ", "DJI", "DJF", "Fdj", 11.8251, 42.5903,
        ("Mobile money (D-Money/Waafi)", "National ID e-KYC"),
        (("Djibouti Region", (("Djibouti City", True),)),)),
    ("Egypt", "EG", "EGY", "EGP", "E£", 30.0444, 31.2357,
        ("Fawry bill payments", "Mobile wallets (Vodafone Cash)", "InstaPay", "National ID e-KYC"),
        (("Cairo Governorate", (("Cairo", True),)), ("Alexandria", (("Alexandria", True),)))),
    ("Equatorial Guinea", "GQ", "GNQ", "XAF", "FCFA", 3.7523, 8.7742,
        ("Mobile money agents", "National ID e-KYC"),
        (("Bioko Norte", (("Malabo", True),)),)),
    ("Eritrea", "ER", "ERI", "ERN", "Nfk", 15.3229, 38.9251,
        ("Mobile banking", "National ID e-KYC"),
        (("Maekel", (("Asmara", True),)),)),
    ("Eswatini", "SZ", "SWZ", "SZL", "L", -26.3054, 31.1367,
        ("MTN Mobile Money", "National ID e-KYC"),
        (("Hhohho", (("Mbabane", True),)),)),
    ("Ethiopia", "ET", "ETH", "ETB", "Br", 9.0250, 38.7469,
        ("Telebirr mobile money", "National ID e-KYC", "Cooperative bank ledgers"),
        (("Addis Ababa", (("Addis Ababa", True),)),)),
    ("Gabon", "GA", "GAB", "XAF", "FCFA", 0.4162, 9.4673,
        ("Mobile money (Airtel/Moov)", "National ID e-KYC"),
        (("Estuaire", (("Libreville", True),)),)),
    ("Gambia", "GM", "GMB", "GMD", "D", 13.4549, -16.5790,
        ("Mobile money (QMoney/Wave)", "National ID e-KYC"),
        (("Banjul", (("Banjul", True),)),)),
    ("Ghana", "GH", "GHA", "GHS", "₵", 5.6037, -0.1870,
        ("MTN Mobile Money", "Ghana QR / GhIPSS instant pay", "National ID e-KYC"),
        (("Greater Accra", (("Accra", True), ("Tema", False))), ("Ashanti", (("Kumasi", True),)))),
    ("Guinea", "GN", "GIN", "GNF", "FG", 9.6412, -13.5784,
        ("Mobile money (Orange Money)", "National ID e-KYC"),
        (("Conakry", (("Conakry", True),)),)),
    ("Guinea-Bissau", "GW", "GNB", "XOF", "CFA", 11.8636, -15.5977,
        ("Mobile money agents", "National ID e-KYC"),
        (("Bissau", (("Bissau", True),)),)),
    ("Ivory Coast", "CI", "CIV", "XOF", "CFA", 5.3600, -4.0083,
        ("Mobile money (Orange/MTN/Moov)", "UEMOA digital rails", "National ID e-KYC"),
        (("Abidjan", (("Abidjan", True),)), ("Yamoussoukro", (("Yamoussoukro", False),)))),
    ("Kenya", "KE", "KEN", "KES", "KSh", -0.0236, 37.9062,
        ("M-Pesa mobile money", "Huduma Namba e-KYC", "Till Number merchant records", "Sacco micro-lending data"),
        (("Nairobi County", (("Nairobi CBD", True), ("Westlands", True), ("Kibera", False))),
         ("Mombasa County", (("Mombasa Island", True), ("Nyali", False))),
         ("Kisumu County", (("Kisumu City", False), ("Ahero", False))),
         ("Nakuru County", (("Nakuru Town", False), ("Naivasha", False))))),
    ("Lesotho", "LS", "LSO", "LSL", "L", -29.3142, 27.4869,
        ("Mobile money (EcoCash/M-Pesa)", "National ID e-KYC"),
        (("Maseru District", (("Maseru", True),)),)),
    ("Liberia", "LR", "LBR", "LRD", "L$", 6.2907, -10.7605,
        ("Mobile money (Orange/Lonestar)", "National ID e-KYC"),
        (("Montserrado", (("Monrovia", True),)),)),
    ("Libya", "LY", "LBY", "LYD", "LD", 32.8872, 13.1913,
        ("Mobile banking", "National ID e-KYC"),
        (("Tripoli", (("Tripoli", True),)),)),
    ("Madagascar", "MG", "MDG", "MGA", "Ar", -18.8792, 47.5079,
        ("Mobile money (Orange/Telma/Airtel)", "National ID e-KYC"),
        (("Analamanga", (("Antananarivo", True),)),)),
    ("Malawi", "MW", "MWI", "MWK", "MK", -13.9626, 33.7741,
        ("Mobile money (Airtel/TNM Mpamba)", "National ID e-KYC"),
        (("Central Region", (("Lilongwe", True),)), ("Southern Region", (("Blantyre", True),)))),
    ("Mali", "ML", "MLI", "XOF", "CFA", 12.6392, -8.0029,
        ("Mobile money (Orange)", "UEMOA digital rails", "National ID e-KYC"),
        (("Bamako", (("Bamako", True),)),)),
    ("Mauritania", "MR", "MRT", "MRU", "UM", 18.0735, -15.9582,
        ("Mobile money (Bankily/Sedad)", "National ID e-KYC"),
        (("Nouakchott", (("Nouakchott", True),)),)),
    ("Mauritius", "MU", "MUS", "MUR", "₨", -20.1609, 57.5012,
        ("MyT Money/Juice mobile banking", "National ID e-KYC", "POS digital payments"),
        (("Port Louis District", (("Port Louis", True),)),)),
    ("Morocco", "MA", "MAR", "MAD", "DH", 34.0209, -6.8417,
        ("Mobile banking apps", "M-Wallet payments", "National ID e-KYC"),
        (("Rabat-Salé-Kénitra", (("Rabat", True),)), ("Casablanca-Settat", (("Casablanca", True),)))),
    ("Mozambique", "MZ", "MOZ", "MZN", "MT", -25.9692, 32.5732,
        ("Mobile money (M-Pesa/e-Mola)", "National ID e-KYC"),
        (("Maputo City", (("Maputo", True),)),)),
    ("Namibia", "NA", "NAM", "NAD", "$", -22.5609, 17.0658,
        ("Mobile banking (eWallet)", "National ID e-KYC"),
        (("Khomas", (("Windhoek", True),)),)),
    ("Niger", "NE", "NER", "XOF", "CFA", 13.5127, 2.1128,
        ("Mobile money (Orange/Airtel)", "UEMOA digital rails", "National ID e-KYC"),
        (("Niamey", (("Niamey", True),)),)),
    ("Nigeria", "NG", "NGA", "NGN", "₦", 9.0820, 8.6753,
        ("Mobile money (OPay, PalmPay, Moniepoint)", "BVN e-KYC", "USSD banking logs", "Paystack/Flutterwave merchant data"),
        (("Lagos", (("Lagos Island", True), ("Ikeja", True), ("Ajah", False))),
         ("Federal Capital Territory", (("Abuja", True), ("Gwagwalada", False))),
         ("Rivers", (("Port Harcourt", True), ("Bonny", False))),
         ("Kano", (("Kano City", False), ("Wudil", False))),
         ("Oyo", (("Ibadan", False), ("Ogbomosho", False))))),
    ("Rwanda", "RW", "RWA", "RWF", "FRw", -1.9441, 30.0619,
        ("Mobile money (MTN MoMo/Airtel)", "Irembo e-gov payments", "National ID e-KYC"),
        (("Kigali", (("Kigali", True),)),)),
    ("Sao Tome and Principe", "ST", "STP", "STN", "Db", 0.3365, 6.7273,
        ("Mobile money agents", "National ID e-KYC"),
        (("São Tomé", (("São Tomé", True),)),)),
    ("Senegal", "SN", "SEN", "XOF", "CFA", 14.7167, -17.4677,
        ("Orange Money/Wave mobile money", "UEMOA digital rails", "National ID e-KYC"),
        (("Dakar", (("Dakar", True),)),)),
    ("Seychelles", "SC", "SYC", "SCR", "₨", -4.6796, 55.4920,
        ("Mobile banking", "National ID e-KYC"),
        (("Mahé", (("Victoria", True),)),)),
    ("Sierra Leone", "SL", "SLE", "SLE", "Le", 8.4657, -13.2317,
        ("Mobile money (Orange/Africell)", "National ID e-KYC"),
        (("Western Area", (("Freetown", True),)),)),
    ("Somalia", "SO", "SOM", "SOS", "Sh", 2.0469, 45.3182,
        ("EVC Plus mobile money", "National ID e-KYC"),
        (("Banaadir", (("Mogadishu", True),)),)),
    ("South Africa", "ZA", "ZAF", "ZAR", "R", -25.7479, 28.2293,
        ("SnapScan/Zapper QR payments", "Instant EFT", "National ID e-KYC"),
        (("Gauteng", (("Johannesburg", True), ("Pretoria", True))), ("Western Cape", (("Cape Town", True),)))),
    ("South Sudan", "SS", "SSD", "SSP", "£", 4.8594, 31.5713,
        ("Mobile money agents", "National ID e-KYC"),
        (("Central Equatoria", (("Juba", True),)),)),
    ("Sudan", "SD", "SDN", "SDG", "SDG", 15.5007, 32.5599,
        ("Mobile banking (Bankak)", "National ID e-KYC"),
        (("Khartoum", (("Khartoum", True),)),)),
    ("Tanzania", "TZ", "TZA", "TZS", "TSh", -6.7924, 39.2083,
        ("M-Pesa/Tigo Pesa mobile money", "National ID e-KYC"),
        (("Dar es Salaam", (("Dar es Salaam", True),)), ("Dodoma", (("Dodoma", False),)))),
    ("Togo", "TG", "TGO", "XOF", "CFA", 6.1725, 1.2314,
        ("Mobile money (Flooz/T-Money)", "UEMOA digital rails", "National ID e-KYC"),
        (("Maritime", (("Lomé", True),)),)),
    ("Tunisia", "TN", "TUN", "TND", "DT", 36.8065, 10.1815,
        ("Mobile banking (D17)", "National ID e-KYC"),
        (("Tunis", (("Tunis", True),)),)),
    ("Uganda", "UG", "UGA", "UGX", "USh", 0.3476, 32.5825,
        ("MTN/Airtel Mobile Money", "National ID e-KYC"),
        (("Central Region", (("Kampala", True),)),)),
    ("Zambia", "ZM", "ZMB", "ZMW", "ZK", -15.3875, 28.3228,
        ("Mobile money (MTN/Airtel)", "National ID e-KYC"),
        (("Lusaka Province", (("Lusaka", True),)),)),
    ("Zimbabwe", "ZW", "ZWE", "ZWL", "Z$", -17.8292, 31.0522,
        ("EcoCash mobile money", "National ID e-KYC"),
        (("Harare", (("Harare", True),)), ("Bulawayo", (("Bulawayo", False),)))),

    # ------------------------------------------------------------------ Asia
    ("Afghanistan", "AF", "AFG", "AFN", "؋", 34.5553, 69.2075,
        ("Mobile money (M-Paisa)", "National ID e-KYC"),
        (("Kabul", (("Kabul", True),)),)),
    ("Armenia", "AM", "ARM", "AMD", "֏", 40.1792, 44.4991,
        ("Mobile banking", "Idram e-wallet", "National ID e-KYC"),
        (("Yerevan", (("Yerevan", True),)),)),
    ("Azerbaijan", "AZ", "AZE", "AZN", "₼", 40.4093, 49.8671,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Baku", (("Baku", True),)),)),
    ("Bahrain", "BH", "BHR", "BHD", "BD", 26.2285, 50.5860,
        ("BenefitPay mobile wallet", "National ID e-KYC"),
        (("Capital Governorate", (("Manama", True),)),)),
    ("Bangladesh", "BD", "BGD", "BDT", "৳", 23.6850, 90.3563,
        ("bKash / Nagad mobile wallets", "NID e-KYC", "SME cluster trade data", "Ready-made garments export ledger"),
        (("Dhaka Division", (("Dhaka", True), ("Narayanganj", True), ("Gazipur", False))),
         ("Chattogram Division", (("Chattogram", True), ("Cox's Bazar", False))),
         ("Khulna Division", (("Khulna", False), ("Jessore", False))),
         ("Rajshahi Division", (("Rajshahi", False), ("Bogura", False))))),
    ("Bhutan", "BT", "BTN", "BTN", "Nu.", 27.4728, 89.6390,
        ("Mobile banking (mBoB)", "National ID e-KYC"),
        (("Thimphu", (("Thimphu", True),)),)),
    ("Brunei", "BN", "BRN", "BND", "$", 4.9031, 114.9398,
        ("BIBD mobile banking", "National ID e-KYC"),
        (("Brunei-Muara", (("Bandar Seri Begawan", True),)),)),
    ("Cambodia", "KH", "KHM", "KHR", "៛", 11.5564, 104.9282,
        ("Bakong digital payment rail", "Wing mobile money", "National ID e-KYC"),
        (("Phnom Penh", (("Phnom Penh", True),)),)),
    ("China", "CN", "CHN", "CNY", "¥", 39.9042, 116.4074,
        ("Alipay", "WeChat Pay", "UnionPay QR payments"),
        (("Beijing", (("Beijing", True),)), ("Shanghai", (("Shanghai", True),)),
         ("Guangdong", (("Guangzhou", True), ("Shenzhen", True))))),
    ("Cyprus", "CY", "CYP", "EUR", "€", 35.1856, 33.3823,
        ("SEPA instant payments", "JCC Smart mobile pay", "National ID e-KYC"),
        (("Nicosia District", (("Nicosia", True),)),)),
    ("Georgia", "GE", "GEO", "GEL", "₾", 41.7151, 44.8271,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Tbilisi", (("Tbilisi", True),)),)),
    ("India", "IN", "IND", "INR", "₹", 22.9734, 78.6569,
        ("UPI real-time payments", "Aadhaar e-KYC", "Bharat Bill Pay (BBPS)", "GST e-invoicing trail"),
        (("Maharashtra", (("Mumbai", True), ("Pune", True), ("Nagpur", False))),
         ("Delhi NCR", (("New Delhi", True), ("Gurugram", True), ("Noida", False))),
         ("Karnataka", (("Bengaluru", True), ("Mysuru", False), ("Mangaluru", False))),
         ("Tamil Nadu", (("Chennai", True), ("Coimbatore", False), ("Madurai", False))),
         ("Gujarat", (("Ahmedabad", True), ("Surat", True), ("Vadodara", False))),
         ("West Bengal", (("Kolkata", True), ("Siliguri", False))))),
    ("Indonesia", "ID", "IDN", "IDR", "Rp", -0.7893, 113.9213,
        ("OVO / GoPay / DANA e-wallets", "QRIS unified QR payments", "Warung merchant ledgers", "KYC via Dukcapil"),
        (("DKI Jakarta", (("Central Jakarta", True), ("South Jakarta", True), ("North Jakarta", False))),
         ("Bali", (("Denpasar", True), ("Ubud", True), ("Singaraja", False))),
         ("West Java", (("Bandung", False), ("Bekasi", False))),
         ("East Java", (("Surabaya", True), ("Malang", False))))),
    ("Iran", "IR", "IRN", "IRR", "﷼", 35.6892, 51.3890,
        ("Shetab card network", "Mobile banking", "National ID e-KYC"),
        (("Tehran", (("Tehran", True),)),)),
    ("Iraq", "IQ", "IRQ", "IQD", "ID", 33.3152, 44.3661,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Baghdad", (("Baghdad", True),)),)),
    ("Israel", "IL", "ISR", "ILS", "₪", 31.7683, 35.2137,
        ("Bit mobile payments", "National ID e-KYC"),
        (("Jerusalem District", (("Jerusalem", True),)), ("Tel Aviv District", (("Tel Aviv", True),)))),
    ("Japan", "JP", "JPN", "JPY", "¥", 35.6762, 139.6503,
        ("PayPay/Suica e-money", "Mobile banking", "National ID e-KYC (My Number)"),
        (("Tokyo", (("Tokyo", True),)), ("Osaka", (("Osaka", True),)))),
    ("Jordan", "JO", "JOR", "JOD", "JD", 31.9454, 35.9284,
        ("JoMoPay mobile money", "National ID e-KYC"),
        (("Amman", (("Amman", True),)),)),
    ("Kazakhstan", "KZ", "KAZ", "KZT", "₸", 51.1694, 71.4491,
        ("Kaspi.kz mobile payments", "National ID e-KYC"),
        (("Astana", (("Astana", True),)), ("Almaty", (("Almaty", True),)))),
    ("Kuwait", "KW", "KWT", "KWD", "KD", 29.3759, 47.9774,
        ("KNET card network", "Mobile banking", "National ID e-KYC"),
        (("Al Asimah", (("Kuwait City", True),)),)),
    ("Kyrgyzstan", "KG", "KGZ", "KGS", "с", 42.8746, 74.5698,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Bishkek", (("Bishkek", True),)),)),
    ("Laos", "LA", "LAO", "LAK", "₭", 17.9757, 102.6331,
        ("BCEL One mobile banking", "National ID e-KYC"),
        (("Vientiane", (("Vientiane", True),)),)),
    ("Lebanon", "LB", "LBN", "LBP", "L£", 33.8938, 35.5018,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Beirut", (("Beirut", True),)),)),
    ("Malaysia", "MY", "MYS", "MYR", "RM", 3.1390, 101.6869,
        ("DuitNow instant payments", "Touch 'n Go eWallet", "National ID e-KYC (MyKad)"),
        (("Kuala Lumpur", (("Kuala Lumpur", True),)), ("Selangor", (("Petaling Jaya", False),)))),
    ("Maldives", "MV", "MDV", "MVR", "Rf", 4.1755, 73.5093,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Malé", (("Malé", True),)),)),
    ("Mongolia", "MN", "MNG", "MNT", "₮", 47.8864, 106.9057,
        ("Mobile banking (Social Pay)", "National ID e-KYC"),
        (("Ulaanbaatar", (("Ulaanbaatar", True),)),)),
    ("Myanmar", "MM", "MMR", "MMK", "K", 16.8409, 96.1735,
        ("Wave Money mobile payments", "National ID e-KYC"),
        (("Yangon", (("Yangon", True),)),)),
    ("Nepal", "NP", "NPL", "NPR", "₨", 27.7172, 85.3240,
        ("eSewa/Khalti mobile wallets", "National ID e-KYC"),
        (("Bagmati", (("Kathmandu", True),)),)),
    ("North Korea", "KP", "PRK", "KPW", "₩", 39.0392, 125.7625,
        ("Limited digital payment infrastructure", "National ID e-KYC"),
        (("Pyongyang", (("Pyongyang", True),)),)),
    ("Oman", "OM", "OMN", "OMR", "﷼", 23.5859, 58.4059,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Muscat", (("Muscat", True),)),)),
    ("Pakistan", "PK", "PAK", "PKR", "₨", 33.6844, 73.0479,
        ("JazzCash/EasyPaisa mobile wallets", "RAAST instant payments", "National ID e-KYC (CNIC)"),
        (("Punjab", (("Lahore", True),)), ("Sindh", (("Karachi", True),)),
         ("Islamabad Capital Territory", (("Islamabad", False),)))),
    ("Palestine", "PS", "PSE", "ILS", "₪", 31.9038, 35.2034,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Ramallah", (("Ramallah", True),)),)),
    ("Philippines", "PH", "PHL", "PHP", "₱", 12.8797, 121.7740,
        ("GCash / Maya e-wallets", "PhilSys National ID", "QR Ph unified payments", "Sari-sari store POS ledgers"),
        (("Metro Manila", (("Makati", True), ("Quezon City", True), ("Taguig", True))),
         ("Cebu", (("Cebu City", True), ("Mandaue", False))),
         ("Davao Region", (("Davao City", False), ("Tagum", False))))),
    ("Qatar", "QA", "QAT", "QAR", "QR", 25.2854, 51.5310,
        ("Mobile banking apps", "National ID e-KYC (QID)"),
        (("Doha", (("Doha", True),)),)),
    ("Saudi Arabia", "SA", "SAU", "SAR", "SR", 24.7136, 46.6753,
        ("mada card network", "STC Pay mobile wallet", "National ID e-KYC (Absher)"),
        (("Riyadh", (("Riyadh", True),)), ("Makkah", (("Jeddah", True),)))),
    ("Singapore", "SG", "SGP", "SGD", "$", 1.3521, 103.8198,
        ("PayNow instant payments", "GrabPay/DBS PayLah!", "National ID e-KYC (Singpass)"),
        (("Central Region", (("Singapore", True),)),)),
    ("South Korea", "KR", "KOR", "KRW", "₩", 37.5665, 126.9780,
        ("KakaoPay/Toss mobile payments", "National ID e-KYC"),
        (("Seoul", (("Seoul", True),)), ("Busan", (("Busan", True),)))),
    ("Sri Lanka", "LK", "LKA", "LKR", "₨", 6.9271, 79.8612,
        ("Mobile banking (Genie/FriMi)", "National ID e-KYC"),
        (("Western Province", (("Colombo", True),)),)),
    ("Syria", "SY", "SYR", "SYP", "LS", 33.5138, 36.2765,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Damascus", (("Damascus", True),)),)),
    ("Taiwan", "TW", "TWN", "TWD", "NT$", 25.0330, 121.5654,
        ("LINE Pay/JKoPay mobile wallets", "National ID e-KYC"),
        (("Taipei", (("Taipei", True),)),)),
    ("Tajikistan", "TJ", "TJK", "TJS", "SM", 38.5598, 68.7870,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Dushanbe", (("Dushanbe", True),)),)),
    ("Thailand", "TH", "THA", "THB", "฿", 13.7563, 100.5018,
        ("PromptPay instant payments", "TrueMoney/Rabbit LINE Pay", "National ID e-KYC"),
        (("Bangkok", (("Bangkok", True),)), ("Chiang Mai", (("Chiang Mai", False),)))),
    ("Timor-Leste", "TL", "TLS", "USD", "$", -8.5569, 125.5603,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Dili", (("Dili", True),)),)),
    ("Turkey", "TR", "TUR", "TRY", "₺", 39.9334, 32.8597,
        ("BKM Express mobile payments", "National ID e-KYC"),
        (("Ankara", (("Ankara", True),)), ("Istanbul", (("Istanbul", True),)))),
    ("Turkmenistan", "TM", "TKM", "TMT", "m", 37.9601, 58.3261,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Ashgabat", (("Ashgabat", True),)),)),
    ("United Arab Emirates", "AE", "ARE", "AED", "AED", 24.4539, 54.3773,
        ("National card scheme", "STC Pay/PayBy mobile wallets", "National ID e-KYC (Emirates ID)"),
        (("Abu Dhabi", (("Abu Dhabi", True),)), ("Dubai", (("Dubai", True),)))),
    ("Uzbekistan", "UZ", "UZB", "UZS", "so'm", 41.2995, 69.2401,
        ("Payme/Click mobile payments", "National ID e-KYC"),
        (("Tashkent", (("Tashkent", True),)),)),
    ("Vietnam", "VN", "VNM", "VND", "₫", 21.0278, 105.8342,
        ("MoMo/ZaloPay e-wallets", "VietQR instant payments", "National ID e-KYC"),
        (("Hanoi", (("Hanoi", True),)), ("Ho Chi Minh City", (("Ho Chi Minh City", True),)))),
    ("Yemen", "YE", "YEM", "YER", "﷼", 15.3694, 44.1910,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Sana'a", (("Sana'a", True),)),)),

    # --------------------------------------------------------------- Europe
    ("Albania", "AL", "ALB", "ALL", "L", 41.3275, 19.8187,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Tirana", (("Tirana", True),)),)),
    ("Andorra", "AD", "AND", "EUR", "€", 42.5063, 1.5218,
        ("SEPA payments", "National ID e-KYC"),
        (("Andorra la Vella", (("Andorra la Vella", True),)),)),
    ("Austria", "AT", "AUT", "EUR", "€", 48.2082, 16.3738,
        ("SEPA instant payments", "Open Banking APIs", "National ID e-KYC"),
        (("Vienna", (("Vienna", True),)),)),
    ("Belarus", "BY", "BLR", "BYN", "Br", 53.9006, 27.5590,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Minsk", (("Minsk", True),)),)),
    ("Belgium", "BE", "BEL", "EUR", "€", 50.8503, 4.3517,
        ("SEPA instant payments", "Payconiq mobile payments", "National ID e-KYC"),
        (("Brussels", (("Brussels", True),)), ("Flanders", (("Antwerp", False),)))),
    ("Bosnia and Herzegovina", "BA", "BIH", "BAM", "KM", 43.8563, 18.4131,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Sarajevo", (("Sarajevo", True),)),)),
    ("Bulgaria", "BG", "BGR", "BGN", "лв", 42.6977, 23.3219,
        ("SEPA/instant payments", "National ID e-KYC"),
        (("Sofia", (("Sofia", True),)),)),
    ("Croatia", "HR", "HRV", "EUR", "€", 45.8150, 15.9819,
        ("SEPA instant payments", "National ID e-KYC"),
        (("Zagreb", (("Zagreb", True),)),)),
    ("Czech Republic", "CZ", "CZE", "CZK", "Kč", 50.0755, 14.4378,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Prague", (("Prague", True),)),)),
    ("Denmark", "DK", "DNK", "DKK", "kr", 55.6761, 12.5683,
        ("MobilePay instant payments", "National ID e-KYC (MitID)"),
        (("Copenhagen", (("Copenhagen", True),)),)),
    ("Estonia", "EE", "EST", "EUR", "€", 59.4370, 24.7536,
        ("SEPA instant payments", "e-Residency digital ID", "National ID e-KYC"),
        (("Tallinn", (("Tallinn", True),)),)),
    ("Finland", "FI", "FIN", "EUR", "€", 60.1699, 24.9384,
        ("MobilePay/Siirto instant payments", "National ID e-KYC"),
        (("Helsinki", (("Helsinki", True),)),)),
    ("France", "FR", "FRA", "EUR", "€", 48.8566, 2.3522,
        ("SEPA instant payments", "Lydia/Paylib mobile payments", "National ID e-KYC"),
        (("Île-de-France", (("Paris", True),)), ("Provence-Alpes-Côte d'Azur", (("Marseille", False),)))),
    ("Germany", "DE", "DEU", "EUR", "€", 52.5200, 13.4050,
        ("SEPA instant payments", "GiroPay/PayPal", "National ID e-KYC"),
        (("Berlin", (("Berlin", True),)), ("Bavaria", (("Munich", True),)),
         ("North Rhine-Westphalia", (("Cologne", False),)))),
    ("Greece", "GR", "GRC", "EUR", "€", 37.9838, 23.7275,
        ("SEPA instant payments", "IRIS mobile payments", "National ID e-KYC"),
        (("Attica", (("Athens", True),)),)),
    ("Hungary", "HU", "HUN", "HUF", "Ft", 47.4979, 19.0402,
        ("Instant payment system (AFR)", "National ID e-KYC"),
        (("Budapest", (("Budapest", True),)),)),
    ("Iceland", "IS", "ISL", "ISK", "kr", 64.1466, -21.9426,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Reykjavik", (("Reykjavik", True),)),)),
    ("Ireland", "IE", "IRL", "EUR", "€", 53.3498, -6.2603,
        ("SEPA instant payments", "National ID e-KYC"),
        (("Dublin", (("Dublin", True),)),)),
    ("Kosovo", "XK", "XKX", "EUR", "€", 42.6629, 21.1655,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Pristina", (("Pristina", True),)),)),
    ("Latvia", "LV", "LVA", "EUR", "€", 56.9496, 24.1052,
        ("SEPA instant payments", "National ID e-KYC"),
        (("Riga", (("Riga", True),)),)),
    ("Liechtenstein", "LI", "LIE", "CHF", "CHF", 47.1660, 9.5554,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Vaduz", (("Vaduz", True),)),)),
    ("Lithuania", "LT", "LTU", "EUR", "€", 54.6872, 25.2797,
        ("SEPA instant payments", "National ID e-KYC"),
        (("Vilnius", (("Vilnius", True),)),)),
    ("Luxembourg", "LU", "LUX", "EUR", "€", 49.6116, 6.1319,
        ("SEPA instant payments", "Digicash mobile payments", "National ID e-KYC"),
        (("Luxembourg City", (("Luxembourg City", True),)),)),
    ("Malta", "MT", "MLT", "EUR", "€", 35.8989, 14.5146,
        ("SEPA instant payments", "National ID e-KYC"),
        (("Valletta", (("Valletta", True),)),)),
    ("Moldova", "MD", "MDA", "MDL", "L", 47.0105, 28.8638,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Chisinau", (("Chisinau", True),)),)),
    ("Monaco", "MC", "MCO", "EUR", "€", 43.7384, 7.4246,
        ("SEPA instant payments", "National ID e-KYC"),
        (("Monaco", (("Monaco", True),)),)),
    ("Montenegro", "ME", "MNE", "EUR", "€", 42.4304, 19.2594,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Podgorica", (("Podgorica", True),)),)),
    ("Netherlands", "NL", "NLD", "EUR", "€", 52.3676, 4.9041,
        ("iDEAL instant payments", "Tikkie mobile payments", "National ID e-KYC"),
        (("North Holland", (("Amsterdam", True),)), ("South Holland", (("Rotterdam", False),)))),
    ("North Macedonia", "MK", "MKD", "MKD", "ден", 41.9981, 21.4254,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Skopje", (("Skopje", True),)),)),
    ("Norway", "NO", "NOR", "NOK", "kr", 59.9139, 10.7522,
        ("Vipps mobile payments", "National ID e-KYC (BankID)"),
        (("Oslo", (("Oslo", True),)),)),
    ("Poland", "PL", "POL", "PLN", "zł", 52.2297, 21.0122,
        ("BLIK instant payments", "National ID e-KYC"),
        (("Masovian", (("Warsaw", True),)), ("Lesser Poland", (("Krakow", False),)))),
    ("Portugal", "PT", "PRT", "EUR", "€", 38.7223, -9.1393,
        ("MB WAY instant payments", "National ID e-KYC"),
        (("Lisbon", (("Lisbon", True),)), ("Porto", (("Porto", False),)))),
    ("Romania", "RO", "ROU", "RON", "lei", 44.4268, 26.1025,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Bucharest", (("Bucharest", True),)),)),
    ("Russia", "RU", "RUS", "RUB", "₽", 55.7558, 37.6173,
        ("Faster Payments System (SBP)", "Mir card network", "National ID e-KYC"),
        (("Moscow", (("Moscow", True),)), ("Saint Petersburg", (("Saint Petersburg", True),)))),
    ("San Marino", "SM", "SMR", "EUR", "€", 43.9424, 12.4578,
        ("Mobile banking apps", "National ID e-KYC"),
        (("San Marino City", (("San Marino City", True),)),)),
    ("Serbia", "RS", "SRB", "RSD", "дин", 44.7866, 20.4489,
        ("Mobile banking apps", "IPS instant payments", "National ID e-KYC"),
        (("Belgrade", (("Belgrade", True),)),)),
    ("Slovakia", "SK", "SVK", "EUR", "€", 48.1486, 17.1077,
        ("SEPA instant payments", "National ID e-KYC"),
        (("Bratislava", (("Bratislava", True),)),)),
    ("Slovenia", "SI", "SVN", "EUR", "€", 46.0569, 14.5058,
        ("SEPA instant payments", "National ID e-KYC"),
        (("Ljubljana", (("Ljubljana", True),)),)),
    ("Spain", "ES", "ESP", "EUR", "€", 40.4168, -3.7038,
        ("Bizum instant payments", "SEPA rails", "National ID e-KYC"),
        (("Madrid", (("Madrid", True),)), ("Catalonia", (("Barcelona", True),)))),
    ("Sweden", "SE", "SWE", "SEK", "kr", 59.3293, 18.0686,
        ("Swish instant payments", "National ID e-KYC (BankID)"),
        (("Stockholm", (("Stockholm", True),)),)),
    ("Switzerland", "CH", "CHE", "CHF", "CHF", 46.9480, 7.4474,
        ("TWINT mobile payments", "National ID e-KYC"),
        (("Zurich", (("Zurich", True),)), ("Bern", (("Bern", False),)))),
    ("Ukraine", "UA", "UKR", "UAH", "₴", 50.4501, 30.5234,
        ("Diia digital ID & payments", "Mobile banking apps", "National ID e-KYC"),
        (("Kyiv", (("Kyiv", True),)),)),
    ("United Kingdom", "GB", "GBR", "GBP", "£", 51.5072, -0.1276,
        ("Faster Payments instant transfers", "Open Banking APIs", "National ID e-KYC"),
        (("England", (("London", True), ("Manchester", False))), ("Scotland", (("Edinburgh", False),)))),
    ("Vatican City", "VA", "VAT", "EUR", "€", 41.9029, 12.4534,
        ("SEPA instant payments", "National ID e-KYC"),
        (("Vatican City", (("Vatican City", True),)),)),

    # ------------------------------------------ North America & Caribbean
    ("Antigua and Barbuda", "AG", "ATG", "XCD", "$", 17.1274, -61.8468,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Saint John", (("St. John's", True),)),)),
    ("Bahamas", "BS", "BHS", "BSD", "$", 25.0343, -77.3963,
        ("Sand Dollar (CBDC)", "Mobile banking apps", "National ID e-KYC"),
        (("New Providence", (("Nassau", True),)),)),
    ("Barbados", "BB", "BRB", "BBD", "$", 13.1132, -59.5988,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Bridgetown", (("Bridgetown", True),)),)),
    ("Belize", "BZ", "BLZ", "BZD", "$", 17.2510, -88.7590,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Belize District", (("Belize City", True),)),)),
    ("Canada", "CA", "CAN", "CAD", "$", 45.4215, -75.6972,
        ("Interac e-Transfer", "Real-Time Rail (RTR)", "National ID e-KYC"),
        (("Ontario", (("Toronto", True), ("Ottawa", False))), ("Quebec", (("Montreal", True),)),
         ("British Columbia", (("Vancouver", True),)))),
    ("Costa Rica", "CR", "CRI", "CRC", "₡", 9.9281, -84.0907,
        ("SINPE Móvil instant payments", "National ID e-KYC"),
        (("San José", (("San José", True),)),)),
    ("Cuba", "CU", "CUB", "CUP", "$", 23.1136, -82.3666,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Havana", (("Havana", True),)),)),
    ("Dominica", "DM", "DMA", "XCD", "$", 15.3092, -61.3794,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Saint George", (("Roseau", True),)),)),
    ("Dominican Republic", "DO", "DOM", "DOP", "RD$", 18.4861, -69.9312,
        ("Mobile wallets (tPago)", "National ID e-KYC"),
        (("Santo Domingo", (("Santo Domingo", True),)),)),
    ("El Salvador", "SV", "SLV", "USD", "$", 13.6929, -89.2182,
        ("Chivo Wallet", "Mobile banking apps", "National ID e-KYC"),
        (("San Salvador", (("San Salvador", True),)),)),
    ("Grenada", "GD", "GRD", "XCD", "$", 12.0561, -61.7488,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Saint George", (("St. George's", True),)),)),
    ("Guatemala", "GT", "GTM", "GTQ", "Q", 14.6349, -90.5069,
        ("Mobile wallets (Tigo Money)", "National ID e-KYC"),
        (("Guatemala", (("Guatemala City", True),)),)),
    ("Haiti", "HT", "HTI", "HTG", "G", 18.5944, -72.3074,
        ("Mobile money (MonCash)", "National ID e-KYC"),
        (("Ouest", (("Port-au-Prince", True),)),)),
    ("Honduras", "HN", "HND", "HNL", "L", 14.0723, -87.1921,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Francisco Morazán", (("Tegucigalpa", True),)),)),
    ("Jamaica", "JM", "JAM", "JMD", "$", 17.9712, -76.7936,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Kingston", (("Kingston", True),)),)),
    ("Mexico", "MX", "MEX", "MXN", "$", 19.4326, -99.1332,
        ("SPEI instant payments", "Mercado Pago/CoDi QR payments", "National ID e-KYC (CURP)"),
        (("Mexico City", (("Mexico City", True),)), ("Jalisco", (("Guadalajara", True),)),
         ("Nuevo León", (("Monterrey", False),)))),
    ("Nicaragua", "NI", "NIC", "NIO", "C$", 12.1150, -86.2362,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Managua", (("Managua", True),)),)),
    ("Panama", "PA", "PAN", "PAB", "B/.", 8.9824, -79.5199,
        ("Yappy mobile payments", "National ID e-KYC"),
        (("Panamá", (("Panama City", True),)),)),
    ("Saint Kitts and Nevis", "KN", "KNA", "XCD", "$", 17.3026, -62.7177,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Saint George Basseterre", (("Basseterre", True),)),)),
    ("Saint Lucia", "LC", "LCA", "XCD", "$", 14.0101, -60.9875,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Castries", (("Castries", True),)),)),
    ("Saint Vincent and the Grenadines", "VC", "VCT", "XCD", "$", 13.1600, -61.2248,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Kingstown", (("Kingstown", True),)),)),
    ("Trinidad and Tobago", "TT", "TTO", "TTD", "$", 10.6596, -61.5019,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Port of Spain", (("Port of Spain", True),)),)),
    ("United States", "US", "USA", "USD", "$", 38.9072, -77.0369,
        ("ACH & FedNow instant payments", "Stripe/Square merchant data", "Alternative credit data (rent, utilities)"),
        (("California", (("Los Angeles", True), ("San Francisco", True))),
         ("New York", (("New York City", True),)),
         ("Texas", (("Houston", True), ("Austin", False))))),

    # ------------------------------------------------------- South America
    ("Argentina", "AR", "ARG", "ARS", "$", -34.6037, -58.3816,
        ("Mercado Pago mobile wallet", "Transferencias 3.0 instant payments", "National ID e-KYC"),
        (("Buenos Aires", (("Buenos Aires", True),)), ("Córdoba", (("Córdoba", False),)))),
    ("Bolivia", "BO", "BOL", "BOB", "Bs.", -16.5000, -68.1500,
        ("Mobile banking apps", "National ID e-KYC"),
        (("La Paz", (("La Paz", True),)),)),
    ("Brazil", "BR", "BRA", "BRL", "R$", -15.8267, -47.9218,
        ("Pix instant payments", "National ID e-KYC (CPF)", "Merchant POS data"),
        (("São Paulo", (("São Paulo", True),)), ("Rio de Janeiro", (("Rio de Janeiro", True),)),
         ("Distrito Federal", (("Brasília", False),)))),
    ("Chile", "CL", "CHL", "CLP", "$", -33.4489, -70.6693,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Santiago Metropolitan", (("Santiago", True),)),)),
    ("Colombia", "CO", "COL", "COP", "$", 4.7110, -74.0721,
        ("PSE/Nequi instant payments", "National ID e-KYC"),
        (("Bogotá", (("Bogotá", True),)), ("Antioquia", (("Medellín", True),)))),
    ("Ecuador", "EC", "ECU", "USD", "$", -0.1807, -78.4678,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Pichincha", (("Quito", True),)), ("Guayas", (("Guayaquil", True),)))),
    ("Guyana", "GY", "GUY", "GYD", "$", 6.8013, -58.1551,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Georgetown", (("Georgetown", True),)),)),
    ("Paraguay", "PY", "PRY", "PYG", "₲", -25.2637, -57.5759,
        ("Mobile wallets (Tigo Money)", "National ID e-KYC"),
        (("Asunción", (("Asunción", True),)),)),
    ("Peru", "PE", "PER", "PEN", "S/", -12.0464, -77.0428,
        ("Yape/Plin mobile wallets", "National ID e-KYC"),
        (("Lima", (("Lima", True),)),)),
    ("Suriname", "SR", "SUR", "SRD", "$", 5.8520, -55.2038,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Paramaribo", (("Paramaribo", True),)),)),
    ("Uruguay", "UY", "URY", "UYU", "$", -34.9011, -56.1645,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Montevideo", (("Montevideo", True),)),)),
    ("Venezuela", "VE", "VEN", "VES", "Bs.", 10.4806, -66.9036,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Caracas", (("Caracas", True),)),)),

    # -------------------------------------------------------------- Oceania
    ("Australia", "AU", "AUS", "AUD", "$", -35.2809, 149.1300,
        ("NPP/PayID instant payments", "National ID e-KYC"),
        (("New South Wales", (("Sydney", True),)), ("Victoria", (("Melbourne", True),)),
         ("Queensland", (("Brisbane", False),)))),
    ("Fiji", "FJ", "FJI", "FJD", "$", -18.1248, 178.4501,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Suva", (("Suva", True),)),)),
    ("Kiribati", "KI", "KIR", "AUD", "$", 1.4518, 172.9717,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Tarawa", (("Tarawa", True),)),)),
    ("Marshall Islands", "MH", "MHL", "USD", "$", 7.1315, 171.1845,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Majuro", (("Majuro", True),)),)),
    ("Micronesia", "FM", "FSM", "USD", "$", 6.9248, 158.1611,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Palikir", (("Palikir", True),)),)),
    ("Nauru", "NR", "NRU", "AUD", "$", -0.5228, 166.9315,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Yaren", (("Yaren", True),)),)),
    ("New Zealand", "NZ", "NZL", "NZD", "$", -41.2865, 174.7762,
        ("Mobile banking apps", "POLi/Online EFTPOS", "National ID e-KYC"),
        (("Wellington", (("Wellington", True),)), ("Auckland", (("Auckland", True),)))),
    ("Palau", "PW", "PLW", "USD", "$", 7.5006, 134.6242,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Koror", (("Koror", True),)),)),
    ("Papua New Guinea", "PG", "PNG", "PGK", "K", -9.4438, 147.1803,
        ("Mobile money (CellMoni)", "National ID e-KYC"),
        (("National Capital District", (("Port Moresby", True),)),)),
    ("Samoa", "WS", "WSM", "WST", "T", -13.8506, -171.7513,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Apia", (("Apia", True),)),)),
    ("Solomon Islands", "SB", "SLB", "SBD", "$", -9.4456, 159.9729,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Honiara", (("Honiara", True),)),)),
    ("Tonga", "TO", "TON", "TOP", "T$", -21.1789, -175.1982,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Nuku'alofa", (("Nuku'alofa", True),)),)),
    ("Tuvalu", "TV", "TUV", "AUD", "$", -8.5199, 179.1990,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Funafuti", (("Funafuti", True),)),)),
    ("Vanuatu", "VU", "VUT", "VUV", "VT", -17.7404, 168.3219,
        ("Mobile banking apps", "National ID e-KYC"),
        (("Port Vila", (("Port Vila", True),)),)),
]

COUNTRIES = _build_countries(_RAW_COUNTRIES)

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
            "below (each 0-100, higher is better), write 5 to 8 short, specific, actionable insight "
            "strings for the business owner. For EVERY factor scoring below 70, include one concrete, "
            "specific recommendation on exactly what the business can change to raise it — reference "
            "real numbers (e.g. a target weekly transaction frequency, a target reduction in inactive "
            "weeks, a target on-time utility payment rate, a safe debt-to-income range, or ways to "
            "build business stability such as formalizing operations or steady staffing). For factors "
            "at or above 70, briefly call out the strength instead. Local Market Demand and "
            "Macroeconomic Context are not directly controllable by the business — note that briefly "
            "rather than inventing an action for them. Respond with ONLY a compact JSON array of "
            'strings, e.g. ["insight one", "insight two", ...]. No markdown fences.\n\n'
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
        text = call_gemini(prompt, temperature=0.6, max_output_tokens=700)
        parsed = _extract_json_block(text)
        if isinstance(parsed, list) and parsed:
            return [str(x)[:260] for x in parsed][:8]
        return fallback_insights
    except Exception:
        return fallback_insights


def build_fallback_insights(context):
    factor_labels = {
        "digital": "Digital Payment Health",
        "utility": "Utility Bill Reliability",
        "stability": "Business Stability",
        "debt": "Debt Burden",
        "demand": "Local Market Demand",
        "macro": "Macroeconomic Context",
    }
    factor_advice = {
        "digital": (
            f"Increase consistent digital transaction volume and weekly frequency in {context['city']} "
            "— aim for revenue-matched digital volume and 20+ payments/week to lift this 35%-weighted factor."
        ),
        "utility": (
            "Set up auto-pay or reminders for utility bills to push your on-time rate toward 95%+ "
            "— one of the fastest, lowest-effort factors to improve."
        ),
        "stability": (
            "Business Stability grows with time in operation, steady staffing, and consistent revenue "
            "growth — formalizing operations and building a longer track record raises this over time."
        ),
        "debt": (
            "Keep combined EMIs below roughly 30-35% of monthly revenue when taking on new credit to "
            "protect this factor and stay well under the 45% warning threshold."
        ),
        "demand": (
            f"Local demand for {context['industry'].lower()} in {context['city']} is a market factor "
            "outside direct control, but diversifying into adjacent, higher-demand offerings can help."
        ),
        "macro": (
            "Reflects national inflation and GDP trends for lender context only — not directly "
            "controllable by an individual business."
        ),
    }
    scored = {k: context[k] for k in factor_labels}
    best_key = max(scored, key=scored.get)

    insights = [
        f"✅ Your strongest factor is {factor_labels[best_key]} at {scored[best_key]}/100 — "
        "lenders will view this favorably."
    ]
    for key, label in factor_labels.items():
        if scored[key] < 70:
            insights.append(f"⚠️ {label} is {scored[key]}/100 — {factor_advice[key]}")

    if context["dti"] > 45:
        insights.append(
            f"Your debt-to-income ratio is {context['dti']}%, above the recommended 45% threshold. "
            "Consider a smaller loan amount or longer tenure."
        )

    if len(insights) == 1:
        insights.append(
            "All six factors are scoring well (70+/100) — keep up your current digital payment and "
            "bill payment habits to maintain this score."
        )
    return insights[:8]


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
