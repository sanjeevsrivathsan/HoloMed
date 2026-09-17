"""HoloMed vision AI service: chest radiograph screening assistance.

Submodules ``model``, ``preprocessing``, ``inference`` and ``explainability``
import torch/torchxrayvision; ``schemas`` does not. Nothing heavy is imported
here so the rest of the backend can start without the vision stack.
"""
