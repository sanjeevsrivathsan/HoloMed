"""Parser regressions for realistic laboratory report layouts (synthetic fixtures only)."""
from backend.services import document_extraction, lab_parser
from backend.services.synthetic_pdf import text_pdf_pages
from backend.tests.synthetic_reports import BLOCK_PAGES, CLEAN_LINES, OCR_TEXT


def _by_name(result):
    return {c.test_name: c for c in result.candidates}


def _parse_block_pdf():
    extracted = document_extraction.extract_text(text_pdf_pages(BLOCK_PAGES))
    assert extracted.method == "pdf_text" and extracted.page_count == 2
    return extracted, lab_parser.parse_report_text(extracted.text)


def test_multi_line_result_blocks_produce_candidates():
    extracted, result = _parse_block_pdf()
    got = _by_name(result)
    # canonical tests
    assert (got["HDL"].value, got["HDL"].unit, got["HDL"].page) == (41.2, "mg/dL", 1)
    assert got["LDL"].value == 138.36 and got["LDL"].source_name == "LDL Cholesterol"
    assert got["Glucose (fasting)"].value == 126.3 and got["Glucose (fasting)"].flag == "high"
    assert got["Glucose (fasting)"].reference_range == "70 - 100"
    assert got["HbA1c"].value == 6.4 and got["HbA1c"].flag == "high"
    assert got["HbA1c"].source_name == "Glycated Haemoglobin (HbA1c)"      # label split across lines
    assert got["Hemoglobin"].value == 12.8
    assert got["WBC"].value == 7900 and got["WBC"].unit == "/cumm"        # thousands separator
    assert got["WBC"].reference_range == "4,000 - 11,000"
    assert (got["Blood Pressure (systolic)"].value, got["Blood Pressure (diastolic)"].value) == (128, 84)
    # decimals preserved exactly as printed
    assert got["Bilirubin (Total)"].value_text == "0.92" and got["Bilirubin (Total)"].value == 0.92
    assert got["SGOT"].value == 17.61 and got["SGOT"].unit == "U/L"
    assert got["Urine Creatinine"].value == 88.36
    assert got["Albumin"].unit == "gm/dl"
    # values without units keep their printed range
    assert got["A/G Ratio"].unit == "" and got["A/G Ratio"].reference_range == "1.1 - 2.2"
    # method/sample lines are never test names
    assert not any(n.lower().startswith(("method", "sample", "note", "biochemistry", "lipid profile"))
                   for n in got)
    # every candidate points to its source page and line
    assert all(c.page in (1, 2) and c.line_text for c in result.candidates)
    assert all("|" in c.line_text for c in result.candidates if not c.test_name.startswith("Blood Pressure"))
    assert all(len(p) <= 48 for p in BLOCK_PAGES)       # fixture fits the synthetic PDF writer


def test_printed_reference_tiers_are_kept_verbatim_and_never_become_flags():
    _, result = _parse_block_pdf()
    got = _by_name(result)
    assert got["HDL"].reference_range == "Desirable > 40.0; Higher Risk < 40.0"
    assert got["Non HDL Cholesterol"].reference_range == \
        "Optimal < 130; Desirable 130-159; Borderline high 160-189"
    assert got["LDL"].reference_range == ("<. 100 mg/dl (Desirable); 100-129 mg/dl (Low risk); "
                                          "130-159 mg/dl (Borderline High); Very High .> 190 mg/dL")
    assert got["Cholesterol/HDL ratio"].reference_range == "Desirable : < 4; Borderline : 4.0 - 6.0"
    assert got["Bilirubin (Direct)"].reference_range == "up to 0.3"
    # "High", "Borderline", "Desirable" in printed tiers are not laboratory flags
    for name in ("HDL", "LDL", "Non HDL Cholesterol", "Cholesterol/HDL ratio", "Total Cholesterol"):
        assert got[name].flag == "unknown", name


def test_unknown_and_qualified_tests_are_never_mapped_by_guessing():
    _, result = _parse_block_pdf()
    names = {c.test_name for c in result.candidates}
    # outside the canonical vocabulary: kept with their printed names
    for printed in ("Total Cholesterol", "Triglycerides", "Non HDL Cholesterol", "VLDL", "Cholesterol/HDL ratio",
                    "Bilirubin (Direct)", "Vitamin D (25-OH)", "Blood Glucose (2 Hr. PP)", "Urine Creatinine"):
        assert printed in names, printed
    # a name/qualifier conflict stays unmapped instead of becoming Hemoglobin or HbA1c
    assert "Haemoglobin (HbA1c)" in names
    assert [c.value for c in result.candidates if c.test_name == "Hemoglobin"] == [12.8]
    assert [c.value for c in result.candidates if c.test_name == "HbA1c"] == [6.4]
    # canonical-looking fragments inside other names do not match
    for name, expected in [("Non HDL Cholesterol", None), ("VLDL", None), ("LDL / HDL ratio", None),
                           ("Blood Glucose (Random)", None), ("Glucose (Post Prandial)", None),
                           ("Creatinine (Urine)", None), ("Random Blood Glucose", None),
                           ("Blood Glucose (Fasting)", "Glucose (fasting)"), ("Plasma Glucose", "Glucose"),
                           ("HbA1c (Glycosylated Hemoglobin)", "HbA1c"), ("Hemoglobin (Hb)", "Hemoglobin"),
                           ("Haemoglobin (HbA1c)", None), ("Total Cholesterol", None)]:
        assert lab_parser.canonical_name(name) == expected, name


def test_dates_are_candidates_with_labels_and_inferred_order():
    _, result = _parse_block_pdf()
    got = [(c.kind, c.value) for c in result.date_candidates]
    # 13/09 and 14/09 can only be day-first, so the document's order is known
    assert got == [("collected", "2026-09-14"), ("registered", "2026-09-13"), ("reported", "2026-09-15")]
    assert result.document_date == "2026-09-14"        # suggestion: collection date
    assert any("more than one date" in w for w in result.warnings)


def test_ambiguous_dates_offer_both_readings():
    lines = ["Registration Time : 05/09/2026 8:05AM Collected on : 05/09/2026 8:40AM",
             "Reported on : 06/09/2026 4:10PM"]
    cands = lab_parser.find_date_candidates(lines)
    assert [(c.kind, c.value, c.alternatives) for c in cands] == [
        ("collected", None, ["2026-09-05", "2026-05-09"]),
        ("registered", None, ["2026-09-05", "2026-05-09"]),
        ("reported", None, ["2026-09-06", "2026-06-09"]),
    ]
    best, warnings = lab_parser.find_document_date(lines)
    assert best is None and "choose it during review" in warnings[0]
    # birth dates are never report dates
    assert lab_parser.find_date_candidates(["Date of Birth: 14/02/1980"]) == []


def test_ocr_spacing_and_glued_dates():
    result = lab_parser.parse_report_text(OCR_TEXT, ocr=True)
    got = {c.test_name: (c.value, c.flag) for c in result.candidates}
    assert got == {"Glucose (fasting)": (112, "high"), "Creatinine": (0.94, "unknown"), "LDL": (138, "high"),
                   "TotalCholesterol": (212, "high"), "Blood Pressure (systolic)": (124, "unknown"),
                   "Blood Pressure (diastolic)": (80, "unknown")}
    assert [(c.kind, c.value) for c in result.date_candidates][0] == ("collected", "2026-09-14")
    assert all(c.confidence != "high" for c in result.candidates)


def test_clean_single_line_reports_still_work():
    result = lab_parser.parse_report_text("\n".join(CLEAN_LINES))
    got = {c.test_name: (c.value, c.unit, c.reference_range, c.flag) for c in result.candidates}
    assert got == {"HbA1c": (7.9, "%", "4.0 - 5.6", "high"), "Hemoglobin": (12.1, "g/dL", "13.0 - 17.0", "low"),
                   "LDL": (162, "mg/dL", "<100", "high")}
    assert result.document_date == "2026-03-14" and result.warnings == []


def test_original_text_is_not_modified_by_parsing():
    extracted, _ = _parse_block_pdf()
    before = extracted.text
    lab_parser.parse_report_text(before)
    assert extracted.text == before
    assert "Sample Collected" not in before and "Collected on : 14/09/2026 8:40AM" in before


def test_numbers_and_slash_values():
    assert lab_parser._to_float("0.92") == 0.92
    assert lab_parser._to_float("88.36") == 88.36
    assert lab_parser._to_float("7,900") == 7900
    assert lab_parser._to_float("3,14") == 3.14
    assert lab_parser._to_float("<100") == 100
    lines = lab_parser.parse_report_text("Blood Pressure\n118/76 mmHg\nBP: 120 / 80").candidates
    assert [(c.test_name, c.value) for c in lines] == [
        ("Blood Pressure (systolic)", 120), ("Blood Pressure (diastolic)", 80),
        ("Blood Pressure (systolic)", 118), ("Blood Pressure (diastolic)", 76)]
