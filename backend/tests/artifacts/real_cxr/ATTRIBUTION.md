# Data attribution

## NIH ChestX-ray14 (NIH Clinical Center)

`source/00000001_000.png` and the images derived from it in this directory
(`original_real_cxr.png`, `real_cxr_preprocessed.png`, `real_cxr_gradcam_heatmap.png`,
`real_cxr_gradcam_overlay.png`, `real_cxr_validation_composite.png`) and the
NIH-based screenshots in `../phase4_e2e/` come from the NIH ChestX-ray14 dataset.

- **Data provider:** the NIH Clinical Center is the data provider.
- **Download site:** https://nihcc.app.box.com/v/ChestXray-NIHCC
- **Citation:** Xiaosong Wang, Yifan Peng, Le Lu, Zhiyong Lu, Mohammadhadi Bagheri, Ronald Summers,
  "ChestX-ray8: Hospital-scale Chest X-ray Database and Benchmarks on Weakly-Supervised
  Classification and Localization of Common Thorax Diseases", IEEE CVPR, pp. 3462–3471, 2017.
- **Usage terms:** the terms as published for this dataset state:
  - "There are no restrictions on the use of the NIH chest x-ray images."
  - Users must provide the download link, cite the paper above, and acknowledge the NIH Clinical
    Center as the data provider.
  - These terms were read on 2026-09-17 from Google Cloud's NIH Chest X-ray dataset page:
    https://docs.cloud.google.com/healthcare-api/docs/resources/public-datasets/nih-chest
  - The NIH Box README itself was not retrieved for this notice.

The copy used here was obtained from the TorchXRayVision repository
(`tests/00000001_000.png`, commit `be1cefcc4967c1143520070fb7d760dc3d485e07`);
see `provenance.json`.

## SIIM-ACR Pneumothorax Segmentation

The SIIM-ACR DICOM used as the secondary validation case, and every image rendered from it,
are **not included** in this repository (see `.gitignore`). Kaggle competition data is subject
to the competition rules, and public redistribution has not been confirmed. Only
non-image results derived from it (model scores in `siim_dicom_real_cxr_scores.json`, metrics
in the validation reports) are included.

## Use in this project

These images were used only for software/pipeline validation. They are not evidence of
diagnostic accuracy. See `docs/REAL_CXR_VALIDATION.md`.
