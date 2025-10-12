"""Tests for amocatlas.writers module."""
import tempfile
import os
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
import pytest

from amocatlas import logger, writers

logger.disable_logging()


@pytest.fixture
def simple_dataset() -> xr.Dataset:
    """Create a simple test dataset."""
    time = pd.date_range("2020-01-01", periods=10, freq="D")
    data = np.random.randn(10)

    ds = xr.Dataset(
        {
            "temperature": (["time"], data, {"units": "degrees_C", "long_name": "Temperature"})
        },
        coords={"time": time},
        attrs={
            "title": "Test dataset",
            "institution": "Test Institution",
            "source": "test data"
        }
    )
    return ds


@pytest.fixture
def dataset_with_problematic_attrs() -> xr.Dataset:
    """Create dataset with attributes that might cause NetCDF writing issues."""
    time = pd.date_range("2020-01-01", periods=5, freq="D")
    data = np.random.randn(5)

    ds = xr.Dataset(
        {
            "data": (["time"], data)
        },
        coords={"time": time},
        attrs={
            "string_attr": "normal string",
            "none_attr": None,  # Problematic
            "bool_attr": True,  # Potentially problematic
            "list_attr": [1, 2, 3],  # Potentially problematic
            "dict_attr": {"nested": "value"},  # Problematic
            "numpy_float": np.float64(3.14),
            "numpy_int": np.int32(42)
        }
    )
    return ds


@pytest.fixture
def ac1_dataset() -> xr.Dataset:
    """Create AC1-compliant dataset with proper 'id' attribute."""
    time = pd.date_range("2020-01-01", periods=5, freq="D")
    transport = np.random.randn(5)

    ds = xr.Dataset(
        {
            "TRANSPORT": (["TIME"], transport, {
                "units": "Sverdrup",
                "long_name": "Ocean Transport"
            })
        },
        coords={"TIME": time},
        attrs={
            "id": "OS_RAPID_20200101-20200105_DP_component_transport",
            "Conventions": "CF-1.8, OceanSITES-1.4",
            "title": "RAPID Transport Data",
            "institution": "NOC"
        }
    )
    return ds


def test_save_dataset_basic(simple_dataset: xr.Dataset) -> None:
    """Test basic dataset saving functionality."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = os.path.join(tmp_dir, "test_output.nc")

        success = writers.save_dataset(simple_dataset, output_file)

        assert success is True
        assert os.path.exists(output_file)

        # Verify we can read it back
        loaded_ds = xr.open_dataset(output_file)
        assert "temperature" in loaded_ds.data_vars
        assert "time" in loaded_ds.coords
        assert loaded_ds.attrs["title"] == "Test dataset"
        loaded_ds.close()


def test_save_dataset_default_path(simple_dataset: xr.Dataset) -> None:
    """Test saving with default path."""
    # Save with default path (should create ../test.nc relative to current directory)
    success = writers.save_dataset(simple_dataset)

    assert success is True

    # Clean up the default file if it was created
    default_file = Path("../test.nc")
    if default_file.exists():
        default_file.unlink()


def test_save_dataset_with_none_attrs() -> None:
    """Test saving dataset with None attributes only."""
    # Create dataset with only None attributes (no dicts which aren't handled in global attrs)
    ds = xr.Dataset(
        {"data": (["x"], [1, 2, 3])},
        attrs={
            "string_attr": "normal string",
            "none_attr": None,  # This should be handled
            "numpy_float": np.float64(3.14),
            "numpy_int": np.int32(42)
        }
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = os.path.join(tmp_dir, "test_none_attrs.nc")

        success = writers.save_dataset(ds, output_file)

        assert success is True
        assert os.path.exists(output_file)

        # Verify None attributes were handled
        loaded_ds = xr.open_dataset(output_file)
        # None should be converted to empty string
        assert loaded_ds.attrs["none_attr"] == ""
        loaded_ds.close()


def test_save_dataset_with_datetime_encoding() -> None:
    """Test datetime variable encoding handling."""
    # Create dataset with datetime variable that has conflicting units
    time = pd.date_range("2020-01-01", periods=5, freq="D")
    ds = xr.Dataset(
        {"data": (["time"], np.random.randn(5))},
        coords={"time": time}
    )

    # Add conflicting attributes that should be removed
    ds["time"].attrs["units"] = "conflicting_units"
    ds["time"].attrs["calendar"] = "conflicting_calendar"

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = os.path.join(tmp_dir, "test_datetime.nc")

        success = writers.save_dataset(ds, output_file)

        assert success is True
        assert os.path.exists(output_file)

        # Verify the file can be read back
        loaded_ds = xr.open_dataset(output_file)
        assert "time" in loaded_ds.coords
        loaded_ds.close()


def test_save_dataset_compression_encoding() -> None:
    """Test that compression encoding is applied."""
    time = pd.date_range("2020-01-01", periods=100, freq="D")
    large_data = np.random.randn(100)

    ds = xr.Dataset(
        {
            "large_var": (["time"], large_data),
            "another_var": (["time"], large_data * 2)
        },
        coords={"time": time}
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = os.path.join(tmp_dir, "test_compression.nc")

        success = writers.save_dataset(ds, output_file)

        assert success is True
        assert os.path.exists(output_file)

        # File should exist and be readable
        loaded_ds = xr.open_dataset(output_file)
        assert loaded_ds["large_var"].shape == (100,)
        loaded_ds.close()


def test_save_dataset_type_conversion_fallback() -> None:
    """Test fallback type conversion when TypeError occurs on variable attributes."""
    # Create dataset with problematic variable attributes (not global attrs)
    ds = xr.Dataset(
        {"data": (["x"], [1, 2, 3])},
        coords={"x": [1, 2, 3]}
    )

    # Add problematic variable attributes that should trigger conversion
    ds["data"].attrs["bool_attr"] = True  # Bool should be converted
    ds["data"].attrs["set_attr"] = set([1, 2, 3])  # Sets should be converted

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = os.path.join(tmp_dir, "test_fallback.nc")

        success = writers.save_dataset(ds, output_file)

        # Should succeed via fallback conversion to strings
        assert success is True
        assert os.path.exists(output_file)


def test_save_dataset_with_global_dict_attrs() -> None:
    """Test that global dict attributes cause failure (not handled by writer)."""
    # Create dataset with dict in global attrs (which writer doesn't handle)
    ds = xr.Dataset(
        {"data": (["x"], [1, 2, 3])},
        attrs={"problematic_dict": {"nested": "value"}}  # This will cause failure
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = os.path.join(tmp_dir, "test_dict_failure.nc")

        success = writers.save_dataset(ds, output_file)

        # Should fail because global dict attrs aren't handled
        assert not success


def test_save_AC1_dataset_basic(ac1_dataset: xr.Dataset) -> None:
    """Test basic AC1 dataset saving."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        result_path = writers.save_AC1_dataset(ac1_dataset, tmp_dir)

        assert isinstance(result_path, Path)
        assert result_path.exists()
        assert result_path.name == "OS_RAPID_20200101-20200105_DP_component_transport.nc"
        assert result_path.parent == Path(tmp_dir)

        # Verify content
        loaded_ds = xr.open_dataset(result_path)
        assert "TRANSPORT" in loaded_ds.data_vars
        assert loaded_ds.attrs["id"] == ac1_dataset.attrs["id"]
        loaded_ds.close()


def test_save_AC1_dataset_string_path(ac1_dataset: xr.Dataset) -> None:
    """Test AC1 saving with string path instead of Path object."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        result_path = writers.save_AC1_dataset(ac1_dataset, tmp_dir)  # tmp_dir is string

        assert isinstance(result_path, Path)
        assert result_path.exists()


def test_save_AC1_dataset_missing_id() -> None:
    """Test AC1 saving with missing 'id' attribute."""
    ds = xr.Dataset(
        {"data": (["x"], [1, 2, 3])},
        attrs={"title": "No ID dataset"}
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(ValueError, match="Global attribute 'id' not found"):
            writers.save_AC1_dataset(ds, tmp_dir)


def test_save_AC1_dataset_save_failure() -> None:
    """Test AC1 saving when underlying save fails due to problematic attributes."""
    # Create dataset with 'id' but problematic attributes that will cause save to fail
    ds = xr.Dataset(
        {"data": (["x"], [1, 2, 3])},
        attrs={
            "id": "test_id",
            "problematic_dict": {"nested": "value"}  # This will cause save to fail
        }
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(RuntimeError, match="Failed to save AC1 dataset"):
            writers.save_AC1_dataset(ds, tmp_dir)


def test_save_dataset_edge_cases() -> None:
    """Test various edge cases in save_dataset."""
    # Test with different numpy types
    ds = xr.Dataset(
        {
            "int32_var": (["x"], np.array([1, 2, 3], dtype=np.int32)),
            "float32_var": (["x"], np.array([1.1, 2.2, 3.3], dtype=np.float32)),
            "float64_var": (["x"], np.array([1.1, 2.2, 3.3], dtype=np.float64))
        },
        attrs={
            "np_int32": np.int32(42),
            "np_float32": np.float32(3.14),
            "np_float64": np.float64(2.718),
            "regular_int": 123,
            "regular_float": 45.6,
            "string_attr": "test string"
        }
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = os.path.join(tmp_dir, "test_types.nc")

        success = writers.save_dataset(ds, output_file)

        assert success is True
        assert os.path.exists(output_file)

        # Verify all data was saved correctly
        loaded_ds = xr.open_dataset(output_file)
        assert "int32_var" in loaded_ds.data_vars
        assert "float32_var" in loaded_ds.data_vars
        assert "float64_var" in loaded_ds.data_vars
        loaded_ds.close()


def test_save_dataset_variable_attributes() -> None:
    """Test handling of variable attributes during save."""
    ds = xr.Dataset({
        "var1": (["x"], [1, 2, 3], {
            "valid_attr": "string",
            "none_attr": None,
            "bool_attr": True,
            "list_attr": [1, 2, 3]
        })
    })

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = os.path.join(tmp_dir, "test_var_attrs.nc")

        success = writers.save_dataset(ds, output_file)

        assert success is True
        assert os.path.exists(output_file)


def test_save_dataset_preserves_original() -> None:
    """Test that save_dataset doesn't modify the original dataset."""
    original_ds = xr.Dataset(
        {"data": (["x"], [1, 2, 3])},
        attrs={"test_attr": None, "other_attr": "value"}
    )

    # Store original state
    original_attrs = dict(original_ds.attrs)

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = os.path.join(tmp_dir, "test_preserve.nc")

        success = writers.save_dataset(original_ds, output_file)

        assert success is True

        # Original dataset should be unchanged
        assert original_ds.attrs == original_attrs
        assert original_ds.attrs["test_attr"] is None  # Should still be None
