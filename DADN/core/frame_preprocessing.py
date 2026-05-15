from __future__ import annotations

import cv2


def preprocess_for_inference(
    frame_bgr,
    *,
    denoise_enabled: bool = True,
    low_light_enabled: bool = True,
):
    result = frame_bgr

    if denoise_enabled:
        result = cv2.medianBlur(result, 3)

    if low_light_enabled:
        ycrcb = cv2.cvtColor(result, cv2.COLOR_BGR2YCrCb)
        y_channel, cr_channel, cb_channel = cv2.split(ycrcb)
        mean_luma = float(y_channel.mean())
        if mean_luma < 95.0:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            y_channel = clahe.apply(y_channel)
            result = cv2.cvtColor(cv2.merge((y_channel, cr_channel, cb_channel)), cv2.COLOR_YCrCb2BGR)

    return result
