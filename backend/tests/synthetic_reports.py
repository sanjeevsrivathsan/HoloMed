"""Synthetic laboratory report layouts for regression tests (no real patient data).

Values, names, identifiers and laboratories are invented. Layouts mirror formats seen
in machine-generated laboratory reports: single-line tables, multi-line result blocks
with method lines and printed reference tiers, OCR output without spaces, labels split
across lines, several labelled dates, and tests outside the canonical vocabulary.
"""

HEADER = [
    "SYNTHETIC DIAGNOSTIC CENTRE - TEST DOCUMENT, NOT REAL PATIENT DATA",
    "Name : Test Subject (synthetic)",
    "Age & Sex : 40 yrs / F Registration Time : 13/09/2026 8:05AM",
    "Ref by : Synthetic Clinic Collected on : 14/09/2026 8:40AM",
    "Patient ID : SYN000000000001 Reported on : 15/09/2026 4:10PM",
    "Test Results Units Reference Range",
]

# Multi-line result blocks, printed tiers, qualifiers, unknown tests — two pages.
BLOCK_PAGES = [
    HEADER + [
        "BIOCHEMISTRY",
        "LIPID PROFILE",
        "Sample: SERUM",
        "Total Cholesterol",
        "Method: CHOD-PAP",
        "212.40 mg/dL 125 - 200",
        "Triglycerides",
        "Method: GOD-PAP",
        "98.10 mg/dL 25 - 150",
        "HDL Cholesterol",
        "Method: Selective Inhibition Method",
        "41.2 mg/dL Desirable     > 40.0",
        "Higher Risk  < 40.0",
        "Non HDL Cholesterol",
        "Method: Calculated",
        "171.20 mg/dL Optimal < 130",
        ",Desirable 130-159",
        ",Borderline high 160-189",
        "LDL Cholesterol",
        "Method: Calculated",
        "138.36 mg/dL <. 100 mg/dl (Desirable)",
        "100-129 mg/dl (Low risk)",
        "130-159 mg/dl (Borderline",
        "High)",
        "Very High .> 190 mg/dL",
        "VLDL",
        "Method: Calculated",
        "19.62 mg/dL 5 - 40",
        "Cholesterol/HDL ratio",
        "Method: Calculated",
        "5.16 Desirable     : < 4",
        "Borderline   :  4.0  - 6.0",
        "Note: Lipid profile is a panel of blood tests. The results of",
        "this test are interpreted by a clinician together with other",
        "information.",
        "LIVER FUNCTION TEST (LFT)",
        "Sample: SERUM",
        "Bilirubin (Total)",
        "Method: Modified TAB",
        "0.92 mg/dL 0 - 1.2",
    ],
    HEADER + [
        "Bilirubin (Direct)",
        "Method: Diazotized sulfanilic Acid",
        "0.21 mg/dL up to 0.3",
        "SGOT",
        "Method: IFCC",
        "17.61 U/L 5 - 40",
        "Albumin",
        "Method: BCG",
        "4.10 gm/dl 3.5 - 5.2",
        "A/G Ratio",
        "Method: Calculated",
        "1.43 1.1 - 2.2",
        "Blood Glucose (Fasting)",
        "Method: GOD-PAP",
        "Sample: NaF-F",
        "126.30 mg/dL 70 - 100 H",
        "Blood Glucose (2 Hr. PP )",
        "Method: GOD-PAP",
        "Sample: NaF-PP",
        "182.50 mg/dL 70 - 140",
        "Glycated",
        "Haemoglobin (HbA1c)",
        "Method: HPLC",
        "6.4 H % 4.0 - 5.6",
        "Haemoglobin (HbA1c)",
        "5.9 % 4.0 - 5.6",
        "Blood Pressure",
        "128/84 mmHg",
        "Vitamin D (25-OH)",
        "Method: CLIA",
        "21.5 ng/mL 30 - 100",
        "Urine Creatinine",
        "88.36 mg/dL 20 - 320",
        "Hemoglobin",
        "12.8 g/dL 12.0 - 15.0",
        "Total Leucocyte Count",
        "7,900 /cumm 4,000 - 11,000",
        "** End of report **",
    ],
]

# The same kind of report as read by OCR: spaces dropped, dates glued to times.
OCR_TEXT = "\n".join([
    "--- Page 1 ---",
    "SYNTHETICDIAGNOSTICCENTRE",
    "SampleCollectedOn:14-Sep-202608:40  ReportDate:15/09/2026",
    "TestName  Result  Unit  Reference Range",
    "FastingBloodGlucose  112H  mg/dL  70-99",
    "SerumCreatinine  0.94  mg/dL  0.70-1.30",
    "LDLCholesterol  138H  mg/dL  <100",
    "TotalCholesterol  212H  mg/dL  <200",
    "BloodPressure:124/80mmHg",
])

# Clean single-line table (the original synthetic format).
CLEAN_LINES = [
    "SYNTHETIC TEST LAB - NOT REAL PATIENT DATA",
    "Collected: 2026-03-14",
    "HbA1c 7.9 % 4.0 - 5.6 H",
    "Hemoglobin 12.1 g/dL 13.0 - 17.0 L",
    "LDL Cholesterol 162 mg/dL <100 H",
]
