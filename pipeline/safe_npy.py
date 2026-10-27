"""
Loading LEMMA-RCA .npy files without running pickled code.

The dataset's .npy files hold Python dictionaries (pod names, arrays, timestamps), which numpy
stores as a pickle. Unpickling can run arbitrary code, so np.load(..., allow_pickle=True) on a
downloaded file is unsafe. This loader accepts plain data (dicts, lists, strings, numbers) and
numpy arrays only, and refuses anything else.
"""

import io
import pickle
from pathlib import Path
from typing import Any, Union

import numpy as np

_ALLOWED = {
    ("numpy", "ndarray"), ("numpy", "dtype"),
    ("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar"),
}


class SafeUnpickler(pickle.Unpickler):
    """Unpickles plain data and numpy arrays only."""

    def find_class(self, module, name):
        if (module, name) in _ALLOWED:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"refusing to load {module}.{name} from a .npy file")


def load_npy(source: Union[str, Path, bytes]) -> Any:
    """Load a .npy file (path or raw bytes). Object arrays are unpickled safely; a 0-d object
    array (how numpy saves a dict) comes back as the object itself."""
    raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    f = io.BytesIO(raw)
    version = np.lib.format.read_magic(f)
    read_header = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                   else np.lib.format.read_array_header_2_0)
    shape, fortran_order, dtype = read_header(f)
    if not dtype.hasobject:
        return np.load(io.BytesIO(raw), allow_pickle=False)
    obj = SafeUnpickler(f).load()
    if isinstance(obj, np.ndarray) and obj.dtype == object and obj.shape == ():
        return obj.item()
    return obj


def save_npy(path: Union[str, Path], obj: Any):
    """Save a dict of plain data and arrays in the same format the dataset uses."""
    np.save(path, obj, allow_pickle=True)
