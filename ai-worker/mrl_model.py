"""MRL checkpoint loading and image embedding helpers.

This module loads the provided ResNet-18 MRL checkpoint and exposes a small
API that can be reused by the RabbitMQ worker and a local smoke-test script.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms
from torchvision.models.resnet import BasicBlock, ResNet
from torchvision.transforms import InterpolationMode

DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parent / "mrl-model" / "resnet18_mrl_cifar100.pt"
DEFAULT_TARGET_DIM = 64


class MRLHead(nn.Module):
    def __init__(self, num_classes: int = 100) -> None:
        super().__init__()
        self.nesting_classifier_0 = nn.Linear(8, num_classes)
        self.nesting_classifier_1 = nn.Linear(16, num_classes)
        self.nesting_classifier_2 = nn.Linear(32, num_classes)
        self.nesting_classifier_3 = nn.Linear(64, num_classes)
        self.nesting_classifier_4 = nn.Linear(128, num_classes)
        self.nesting_classifier_5 = nn.Linear(256, num_classes)
        self.nesting_classifier_6 = nn.Linear(512, num_classes)


class MRLResNet18(ResNet):
    def __init__(self) -> None:
        super().__init__(block=BasicBlock, layers=[2, 2, 2, 2], num_classes=100)
        self.fc = MRLHead(num_classes=100)

    def forward_features(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        x = self.avgpool(x)
        return torch.flatten(x, 1)


def load_model(weights_path: Path = DEFAULT_WEIGHTS_PATH) -> MRLResNet18:
    model = MRLResNet18()
    state_dict = torch.load(weights_path, map_location="cpu")
    model.load_state_dict(state_dict, strict=True)
    
    # Set to eval mode since we're only using it for inference.
    model.eval()
    return model


MODEL = load_model()

PREPROCESS = transforms.Compose(
    [
        transforms.Resize((224, 224), interpolation=InterpolationMode.BICUBIC),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    ]
)


def extract_embedding_from_image(image: Image.Image, target_dim: int = DEFAULT_TARGET_DIM) -> torch.Tensor:
    if image.mode != "RGB":
        image = image.convert("RGB")

    tensor = PREPROCESS(image).unsqueeze(0)
    with torch.no_grad():
        features = MODEL.forward_features(tensor)
        embedding = features[:, :target_dim]
        embedding = F.normalize(embedding, dim=1)
    return embedding.squeeze(0)


def extract_embedding_from_bytes(image_base64: str, target_dim: int = DEFAULT_TARGET_DIM) -> torch.Tensor:
    if not image_base64:
        raise ValueError("image_base64 is empty")

    raw_bytes = base64.b64decode(image_base64)
    image = Image.open(BytesIO(raw_bytes))
    return extract_embedding_from_image(image, target_dim=target_dim)
