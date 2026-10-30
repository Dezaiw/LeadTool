"""Text from a picture with Windows' own OCR (offline, the languages
installed in Windows - English / Russian)."""
import asyncio

from PySide6 import QtCore, QtGui


def recognize(image: QtGui.QImage) -> str:
    try:
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter
    except ImportError:
        return ""
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return ""
    # small text reads better a bit larger
    if image.width() < 1200:
        image = image.scaled(image.width() * 2, image.height() * 2,
                             QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                             QtCore.Qt.TransformationMode.SmoothTransformation)
    image = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    w, h = image.width(), image.height()
    raw = bytes(image.constBits())[: w * h * 4]
    writer = DataWriter()
    writer.write_bytes(raw)
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.RGBA8, w, h)

    async def run():
        result = await engine.recognize_async(bitmap)
        return "\n".join(line.text for line in result.lines)
    try:
        return asyncio.run(run()).strip()
    except Exception:                                            # noqa: BLE001
        return ""
