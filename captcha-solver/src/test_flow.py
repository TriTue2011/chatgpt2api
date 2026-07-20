"""Quick test of Flow generate_image with the new fetch() approach."""
import asyncio
import json
import logging
import sys

# Run from captcha-solver/ parent so src is the package
# Usage: cd captcha-solver && python -m src.test_flow

from .solvers.flow_google import generate_image, get_or_create_project

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main():
    # 1) Get or create a Flow project
    print("--- Getting Flow project ---")
    project = await get_or_create_project(
        profile="google-fx",
        headless=False,
        timeout=90,
    )
    print(json.dumps(project, indent=2, ensure_ascii=False))

    # 2) Generate image
    print("\n--- Generating image ---")
    result = await generate_image(
        project_id=project["project_id"],
        prompt="mèo đuổi chuột trong vườn chuối việt nam",
        aspect_ratio="IMAGE_ASPECT_RATIO_LANDSCAPE",
        model="NANO_BANANA_PRO",
        count=1,
        profile="google-fx",
        headless=False,
        timeout=120,
    )

    images = result.pop("images", [])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n--- {len(images)} image(s) ---")
    for img in images:
        print(f"  url={img.get('url', '')[:100]}")
        print(f"  seed={img.get('seed')}")
        print(f"  model={img.get('model')}")


if __name__ == "__main__":
    asyncio.run(main())
