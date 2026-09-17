"""Validated model identity (torch-free, shared by local, cloud and explanation code)."""

MODEL_NAME = "TorchXRayVision DenseNet-121"
ARCHITECTURE = "DenseNet-121 (growth 32, blocks 6/12/24/16, 1 input channel, 18 outputs)"
WEIGHTS_ID = "densenet121-res224-all"
EXPECTED_SHA256 = "56524913dd16a906422e8d8b66a7a5c46be1d82eb7ac012d8103776f1aa68899"
EXPECTED_TARGETS = [
    "Atelectasis", "Consolidation", "Infiltration", "Pneumothorax", "Edema",
    "Emphysema", "Fibrosis", "Effusion", "Pneumonia", "Pleural_Thickening",
    "Cardiomegaly", "Nodule", "Mass", "Hernia", "Lung Lesion", "Fracture",
    "Lung Opacity", "Enlarged Cardiomediastinum",
]
INPUT_SIZE = 224
TARGET_LAYER = "features.denseblock4"
