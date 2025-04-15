import numpy as np
import base64
import logging
from typing import Union

logger = logging.getLogger(__name__)

def float_to_16bit_pcm(float32_array: np.ndarray) -> np.ndarray:
    """
    Converts a numpy array of float32 amplitude data to int16 format.

    Args:
        float32_array (np.ndarray): Input float32 numpy array.

    Returns:
        np.ndarray: Output int16 numpy array.
    """
    if float32_array.dtype != np.float32:
        raise ValueError("Input array must be float32 dtype")

    int16_array = np.clip(float32_array, -1.0, 1.0) * 32767
    return int16_array.astype(np.int16)

def base64_to_array_buffer(base64_string: str, dtype: np.dtype = np.uint8) -> np.ndarray:
    """
    Converts a base64 encoded string to a numpy array buffer.

    Args:
        base64_string (str): Base64 encoded string.
        dtype (np.dtype, optional): Target dtype for the array. Defaults to uint8.

    Returns:
        np.ndarray: Decoded numpy array buffer.
    """
    binary_data = base64.b64decode(base64_string)
    return np.frombuffer(binary_data, dtype=dtype)

def array_buffer_to_base64(array_buffer: np.ndarray) -> str:
    """
    Converts a numpy array buffer to a base64 encoded string.

    Args:
        array_buffer (np.ndarray): Input numpy array.

    Returns:
        str: Base64 encoded string.
    """
    if array_buffer.dtype == np.float32:
        array_buffer = float_to_16bit_pcm(array_buffer)
    elif array_buffer.dtype not in (np.int16, np.uint8):
        raise ValueError(f"Unsupported array_buffer dtype: {array_buffer.dtype}")

    array_buffer_bytes = array_buffer.tobytes()
    return base64.b64encode(array_buffer_bytes).decode('utf-8')

def merge_int16_arrays(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """
    Merges two numpy arrays into one.

    Args:
        left (np.ndarray): First numpy array.
        right (np.ndarray): Second numpy array.

    Returns:
        np.ndarray: Concatenated array.

    Raises:
        ValueError: If inputs are not both int16 numpy arrays with the same dtype.
    """
    if not (isinstance(left, np.ndarray) and isinstance(right, np.ndarray)):
        raise ValueError("Both items must be numpy arrays")

    if left.dtype != np.int16 or right.dtype != np.int16:
        raise ValueError("Both arrays must have dtype int16")

    return np.concatenate((left, right))
