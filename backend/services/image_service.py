import asyncio
from io import BytesIO
from PIL import Image
from backend.config import settings


class ImageService:
    def __init__(self):
        self.max_width = settings.MAX_IMAGE_WIDTH
        self.max_height = settings.MAX_IMAGE_HEIGHT

    async def resize_and_save(self, image_bytes: bytes, output_path: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._resize_sync, image_bytes, output_path)

    def _resize_sync(self, image_bytes: bytes, output_path: str) -> None:
        img = Image.open(BytesIO(image_bytes))

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        img.thumbnail((self.max_width, self.max_height), Image.LANCZOS)

        # Pad to exact size if needed
        if img.size != (self.max_width, self.max_height):
            new_img = Image.new("RGB", (self.max_width, self.max_height), (255, 255, 255))
            offset = (
                (self.max_width - img.width) // 2,
                (self.max_height - img.height) // 2,
            )
            new_img.paste(img, offset)
            img = new_img

        img.save(output_path, "JPEG", quality=85, optimize=True)

    async def resize_and_save_slip(self, image_bytes: bytes, output_path: str) -> None:
        """Resize slip images to fit within max dimensions without padding."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._resize_slip_sync, image_bytes, output_path)

    def _resize_slip_sync(self, image_bytes: bytes, output_path: str) -> None:
        img = Image.open(BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((self.max_width, self.max_height), Image.LANCZOS)
        img.save(output_path, "JPEG", quality=85, optimize=True)

    async def get_thumbnail(self, image_bytes: bytes, width: int = 400, height: int = 300) -> bytes:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._thumbnail_sync, image_bytes, width, height)

    def _thumbnail_sync(self, image_bytes: bytes, width: int, height: int) -> bytes:
        img = Image.open(BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((width, height), Image.LANCZOS)
        output = BytesIO()
        img.save(output, "JPEG", quality=75)
        return output.getvalue()
