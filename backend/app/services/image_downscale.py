"""用户上传照片的模型调用前压缩。

手机/相机原图动辄 4-8MB，base64 后塞进视觉模型会让上传和推理都慢一倍
以上（实测 4.7MB 原图拍照批改要 80 秒）。压到长边 1600 的 JPEG 后文字
辨识度不受影响，调用时间大幅下降。
"""

from io import BytesIO

from PIL import Image

MAX_SIDE = 1600
JPEG_QUALITY = 85
# 小于这个体积且尺寸达标就不动，避免无谓的重编码
SKIP_BYTES = 800 * 1024


def downscale_image_for_model(
    image_bytes: bytes, *, max_side: int = MAX_SIDE, quality: int = JPEG_QUALITY
) -> bytes:
    try:
        image = Image.open(BytesIO(image_bytes))
    except OSError:
        return image_bytes
    if max(image.size) <= max_side and len(image_bytes) <= SKIP_BYTES:
        return image_bytes
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
