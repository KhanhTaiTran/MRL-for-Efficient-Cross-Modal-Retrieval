from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from model import DEFAULT_TARGET_DIM, extract_embedding_from_image
from PIL import Image, ImageDraw


# simple smoke test to verify the MRL checkpoint can be loaded and produces a 64-dim embedding from an image
def create_demo_image(path: Path) -> Path:
    image = Image.new("RGB", (256, 256), color=(24, 44, 72)) 
    draw = ImageDraw.Draw(image)
    draw.rectangle((32, 32, 224, 224), outline=(255, 195, 0), width=8)
    draw.text((64, 112), "MRL", fill=(255, 255, 255))
    image.save(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test the MRL checkpoint and print a 64-dim embedding.")
    parser.add_argument("--image", type=Path, help="Path to an input image. If omitted, a demo image is generated.")
    parser.add_argument("--dim", type=int, default=DEFAULT_TARGET_DIM, help="Target embedding dimension.")
    args = parser.parse_args()

    if args.image is None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = create_demo_image(Path(tmp_dir) / "demo-mrl.png")
            embedding = extract_embedding_from_image(Image.open(image_path), target_dim=args.dim)
    else:
        embedding = extract_embedding_from_image(Image.open(args.image), target_dim=args.dim)

    values = [round(value, 6) for value in embedding.tolist()]
    print(f"shape={list(embedding.shape)}")
    print(values)


if __name__ == "__main__":
    main()