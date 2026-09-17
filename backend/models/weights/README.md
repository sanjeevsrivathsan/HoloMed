# Vision model weights

The vision service loads a local checkpoint and never downloads weights at runtime.
The checkpoint file is **not committed** to this repository (see `.gitignore`).

| | |
|---|---|
| Expected path | `backend/models/weights/densenet121-res224-all.pt` (override with `VISION_WEIGHTS_PATH`) |
| Model | TorchXRayVision DenseNet-121, weights `densenet121-res224-all` |
| Upstream file | https://github.com/mlmed/torchxrayvision/releases/download/v1/nih-pc-chex-mimic_ch-google-openi-kaggle-densenet121-d121-tw-lr001-rot45-tr15-sc15-seed0-best.pt |
| Size | 28,382,008 bytes |
| SHA-256 | `56524913dd16a906422e8d8b66a7a5c46be1d82eb7ac012d8103776f1aa68899` |

## Setup

1. Download the upstream file to `densenet121-res224-all.pt` in this directory.
2. Verify its hash:

   ```bash
   python -c "import hashlib;print(hashlib.sha256(open('backend/models/weights/densenet121-res224-all.pt','rb').read()).hexdigest())"
   ```

The service verifies this SHA-256 **before** deserializing the checkpoint and returns
HTTP 503 if the file is missing or the hash differs.
