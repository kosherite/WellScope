"""Source URLs and defaults. Every URL here was taken from the publisher's own download page; if a
publisher moves a file, change it here and nowhere else."""
from __future__ import annotations

PETRINEX_VOL = "https://www.petrinex.gov.ab.ca/publicdata/API/Files/{jur}/Vol/{month}/CSV"
PETRINEX_INFRA = "https://www.petrinex.gov.ab.ca/publicdata/API/Files/{jur}/Infra/{name}/CSV"

SOURCES = {
    "AB": {
        "name": "Alberta",
        "wells": "https://www.aer.ca/prd/documents/sts/st37/ST_37_Excel.zip",          # AER ST37 Excel package
        "petrinex": "AB",
        "infra": ["Well Infrastructure", "Well to Facility Link", "Facility Infrastructure", "Business Associate"],
        "pages": ["https://www.aer.ca/data-and-performance-reports/statistical-reports/st37",
                  "https://www.petrinex.ca/public-data/apd/"],
    },
    "SK": {
        "name": "Saskatchewan",
        "petrinex": "SK",
        "infra": ["Well Infrastructure", "Well Licence", "Well to Facility Link", "Facility Infrastructure", "Business Associate"],
        "pages": ["https://www.petrinex.ca/public-data/spd/"],
    },
    "BC": {
        "name": "British Columbia",
        "well_index": "https://iris.bcogc.ca/download/well_index.csv",
        "production": "https://iris.bcogc.ca/download/prod_csv.zip",
        "drilling": "https://iris.bcogc.ca/download/drill_csv.zip",
        "frac": "https://iris.bcogc.ca/download/hydraulic_fracture_csv.zip",
        "pages": ["https://www.bc-er.ca/data-reports/data-centre"],
    },
    "MB": {
        "name": "Manitoba",
        "production": [
            "https://www.gov.mb.ca/iem/petroleum/reports/wmp_2023_2026_excel.zip",
            "https://www.gov.mb.ca/iem/petroleum/reports/wmp_2021_2022_excel.zip",
        ],
        "uwi_list": "https://www.gov.mb.ca/iem/petroleum/reports/uwi_weekly.xlsx",
        "new_wells": "https://www.gov.mb.ca/iem/petroleum/reports/new_well_license_approvals_coordinates.xlsx",
        "company_codes": "https://www.gov.mb.ca/iem/petroleum/reports/company_codes.xlsx",
        "pages": ["https://www.gov.mb.ca/iem/petroleum/reports/index.html"],
    },
}

# Units
M3_TO_BBL = 6.28981
E3M3_TO_MCF = 35.3147        # 1,000 m3 of gas = 35.3147 mcf
MCF_PER_BOE = 6.0            # industry 6:1 convention (primer: "6 mcf = 1 boe")
GJ_PER_MCF = 1.055

# Analysis defaults (overridable from the CLI and in the website's price deck)
DEFAULTS = {
    "months": 36,
    "type_curve_months": 36,       # months-on-production shown in type curves
    "min_wells_type_curve": 5,
    "cleanup_base": 80_000,         # $ per inactive well, placeholder (not the AER's liability method)
    "cleanup_per_m": 55,            # $ per metre of depth, placeholder
}

PRICE_DECK = {                      # shipped to the website as the starting deck; users can change it there
    "wti_usd": 70.0,
    "fx_usdcad": 0.73,
    "oil_diff_usd": 5.0,            # light oil differential to WTI (Edmonton); heavy blends are wider
    "aeco_cad_gj": 2.50,
    "royalty": 0.15,
    "opex_cad_boe": 14.0,
    "transport_cad_boe": 2.5,
    "discount": 0.10,
}
