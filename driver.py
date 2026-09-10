"""
BioLogic potentiostat driver.

Public methods decorated with ``@command`` are advertised on NATS. Helpers stay
private (leading underscore). Technique handlers accept either a ``params`` dict
or flat keyword arguments::

    driver.CV(params={"start": 0.0, "end": 0.5}, channels=[0])
    driver.CV(start=0.0, end=0.5, channels=[0])
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Type

from puda import command, safety

logger = logging.getLogger(__name__)

# EC-Lab native libraries are Windows-only.
if sys.platform == "win32":
    import puda_biologic as ebl
    import puda_biologic.base_programs as blp
    from puda_biologic.lib import ec_lib
else:
    ebl = None
    blp = None
    ec_lib = None


class _Params(dict):
    """Dict that also allows attribute access for easy_biologic programs."""

    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(f"'_Params' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        self[name] = value


def _convert_irange_string(irange_str: str):
    """
    Convert a string representation of IRange to the actual IRange object.

    Supports formats:
    - "IRange.m10" -> IRange.m10
    - "m10" -> IRange.m10

    Args:
        irange_str: String representation of IRange (e.g., "IRange.m10" or "m10")

    Returns:
        IRange object if conversion successful, otherwise returns the original string

    Raises:
        ValueError: If the string doesn't match a valid IRange value
    """
    if not isinstance(irange_str, str):
        return irange_str

    if irange_str.startswith("IRange."):
        irange_name = irange_str[7:]
    else:
        irange_name = irange_str

    try:
        return getattr(ec_lib.IRange, irange_name)
    except AttributeError:
        raise ValueError(
            f"Invalid IRange value: {irange_str}. Valid values are: p100, n1, u1, m1, m10, a1, AUTO"
        )


def _convert_erange_string(erange_str: str):
    """
    Convert a string representation of ERange to the actual ERange object.

    Supports formats:
    - "ERange.v2_5" -> ERange.v2_5
    - "v2_5" -> ERange.v2_5

    Args:
        erange_str: String representation of ERange (e.g., "ERange.v10" or "v10")

    Returns:
        ERange object if conversion successful, otherwise returns the original string

    Raises:
        ValueError: If the string doesn't match a valid ERange value
    """
    if not isinstance(erange_str, str):
        return erange_str

    if erange_str.startswith("ERange."):
        erange_name = erange_str[7:]
    else:
        erange_name = erange_str

    try:
        return getattr(ec_lib.ERange, erange_name)
    except AttributeError:
        raise ValueError(
            f"Invalid ERange value: {erange_str}. Valid values are: v2_5, v5, v10, AUTO"
        )


class Driver:
    """BioLogic potentiostat. Runs EC-Lab techniques (OCV, CA, CP, CV, PEIS, GEIS, MPP) over Ethernet."""

    _META_KEYS = frozenset({
        "channels", "retrieve_data", "data", "by_channel", "cv", "folder",
    })

    @staticmethod
    def _split_kwargs(all_kwargs: dict) -> tuple[dict, dict]:
        """Separate program params from constructor/run meta kwargs."""
        meta = {}
        params = {}
        for k, v in all_kwargs.items():
            if k in Driver._META_KEYS:
                meta[k] = v
            else:
                params[k] = v
        return params, meta

    def __init__(self, device_ip: str):
        """
        Connect to the BioLogic instrument.

        Args:
            device_ip: Ethernet address of the potentiostat
        """
        self.device_ip = device_ip
        self.device = None
        self._startup()

    def _startup(self) -> None:
        """Open the EC-Lab device connection."""
        if ebl is None:
            raise RuntimeError(
                "BioLogic EC-Lab libraries are only available on Windows. "
                f"Current platform: {sys.platform}"
            )
        if self.device is not None:
            logger.warning("BiologicDevice already initialized, skipping startup")
            return
        self.device = ebl.BiologicDevice(self.device_ip)
        logger.info("BiologicDevice started with IP: %s", self.device_ip)

    def _disconnect(self) -> None:
        """Best-effort close of the EC-Lab connection."""
        if self.device is None:
            return
        disconnect = getattr(self.device, "disconnect", None)
        if callable(disconnect):
            disconnect()
        self.device = None
        logger.info("BiologicDevice disconnected")

    def snapshot(self) -> dict:
        """Connection fields merged into MACHINE_STATE KV updates."""
        return {
            "connected": self.device is not None,
            "device_ip": self.device_ip,
        }

    def _run_base_program(
        self,
        program_class: Type[Any],
        params: dict[str, Any],
        **kwargs
    ) -> dict[str, Any]:
        """
        Generic helper method to run any base program.

        This method handles the common pattern:
        1. Create the program instance with params and kwargs
        2. Run the program (with appropriate signature)
        3. Return the data

        Args:
            program_class: The base program class to instantiate (e.g., blp.OCV, blp.CA)
            params: Dictionary of parameters for the program
            **kwargs: Additional keyword arguments:
                - For standard programs: retrieve_data [Default: True]
                - For MPP/MPP_Cycles: data, by_channel, cv
                - channels: List of channel numbers (for constructor). [Required]

        Returns:
            Dictionary containing the program data

        Raises:
            RuntimeError: If the device is not connected
            ValueError: If channels is missing
        """
        if self.device is None:
            raise RuntimeError("Device not initialized. Call reset() before running programs.")
        if "channels" not in kwargs or kwargs["channels"] is None:
            raise ValueError("'channels' is required and must be provided for all programs.")
        if "current_range" in params and isinstance(params["current_range"], str):
            try:
                params["current_range"] = _convert_irange_string(params["current_range"])
            except (ValueError, AttributeError) as e:
                logger.warning(
                    "Failed to convert current_range string '%s' to IRange object: %s. Using as-is.",
                    params["current_range"], e,
                )

        if "voltage_range" in params and isinstance(params["voltage_range"], str):
            try:
                params["voltage_range"] = _convert_erange_string(params["voltage_range"])
            except (ValueError, AttributeError) as e:
                logger.warning(
                    "Failed to convert voltage_range string '%s' to ERange object: %s. Using as-is.",
                    params["voltage_range"], e,
                )

        params = _Params(params)

        if issubclass(program_class, blp.MPP):
            data = kwargs.pop("data", "data")
            by_channel = kwargs.pop("by_channel", False)
            cv_params = kwargs.pop("cv", {})
            run_kwargs = {"data": data, "by_channel": by_channel, "cv": cv_params}
        elif program_class == blp.MPP_Tracking:
            folder = kwargs.pop("folder", None)
            by_channel = kwargs.pop("by_channel", False)
            run_kwargs = {"folder": folder, "by_channel": by_channel}
        else:
            retrieve_data = kwargs.pop("retrieve_data", True)
            run_kwargs = {"retrieve_data": retrieve_data}

        program = program_class(
            device=self.device,
            params=params,
            **kwargs
        )

        program.run(**run_kwargs)

        return program.data

    @command
    def shutdown(self) -> bool:
        """
        Release the EC-Lab connection. Used on edge restart.

        Returns:
            bool: True if the connection was released
        """
        self._disconnect()
        return True

    @command
    def home(self) -> bool:
        """
        Confirm the potentiostat is connected. There is no mechanical home.

        Returns:
            bool: True if the device is connected

        Raises:
            RuntimeError: If the device is not connected
        """
        if self.device is None:
            raise RuntimeError("Device not connected. Call reset() first.")
        logger.info("Home is a no-op on BioLogic; device is connected at %s", self.device_ip)
        return True

    @command
    @safety(
        summary="Drops and reopens the EC-Lab session, aborting any running technique.",
        hazards=["electrical"],
        requires="No measurement should be in progress unless aborting it is intended.",
    )
    def reset(self) -> bool:
        """
        Software reset. Disconnects and reconnects the potentiostat.

        Returns:
            bool: True if the device reconnected

        Raises:
            RuntimeError: If reconnection fails
        """
        self._disconnect()
        self._startup()
        return True

    @command
    def OCV(
        self,
        params: dict[str, Any] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        Run OCV (Open Circuit Voltage) test.

        Args:
            params: Dictionary containing:
                - time: Test duration in seconds (float, > 0). [Required]
                - time_interval: Maximum time between readings (float, > 0.0002 s). [Default: 1]
                - voltage_interval: Maximum interval between voltage readings (float, 1e-6 to 1 V). [Default: 0.01]
                - channels: List of channel numbers. [Required]
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]

        Returns:
            Dict[str, List[List[float]]]: Channel-keyed measurement data.

            Data schema (OCV):
                row = [potential, current, time, extra, flag]
                primary_x = "time"
                primary_y = "potential"

                Index | Name      | Unit | Meaning
                ------|-----------|------|-----------------------------------------
                0     | potential | V    | Working electrode potential
                1     | current   | A    | Measured current
                2     | time      | s    | Elapsed time
                3     | extra     | -    | Internal metadata/auxiliary value
                4     | flag      | -    | Status/cycle boundary indicator
        """
        if params is None:
            params, kwargs = self._split_kwargs(kwargs)
        logger.info("Running OCV test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.OCV, params, **kwargs)

    @command
    def CA(
        self,
        params: dict[str, Any] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        Run CA (Chronoamperometry) test.

        Args:
            params: Dictionary containing:
                - voltages: List of voltages in Volts (list[float], each element: -10 to 10 V). [Required]
                - durations: List of times in seconds (list[float], each element: > 0). [Required]
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points (float, 0.0002 to 1000 s). [Default: 1]
                - current_interval: Maximum current change between points (float, ±1e-12 to current_range A). [Default: 0.001]
                - current_range: Current range. Use ec_lib.IRange (typically ±1 A). Available: IRange.p100 (±100 pA), IRange.n1 (±1 nA), IRange.u1 (±1 µA), IRange.m1 (±1 mA), IRange.m10 (±10 mA), IRange.a1 (±1 A). Can be provided as a string (e.g., "IRange.m10") which will be automatically converted. [Default: IRange.m10]
                - channels: List of channel numbers. [Required]
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]

        Returns:
            Dict[str, List[List[float]]]: Channel-keyed measurement data.

            Data schema (CA):
                row = [time, current, voltage, extra, flag]
                primary_x = "time"
                primary_y = "current"

                Index | Name    | Unit | Meaning
                ------|---------|------|-----------------------------------------
                0     | time    | s    | Elapsed time
                1     | current | A    | Measured current
                2     | voltage | V    | Applied/measured voltage
                3     | extra   | -    | Internal metadata/auxiliary value
                4     | flag    | -    | Status/step boundary indicator
        """
        if params is None:
            params, kwargs = self._split_kwargs(kwargs)
        logger.info("Running CA test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.CA, params, **kwargs)

    @command
    def CP(
        self,
        params: dict[str, Any] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        Run CP (Chronopotentiometry) test.

        Args:
            params: Dictionary containing:
                - currents: List of currents in Amps. (list[float], each element: 1e-9 to current_range A) [Required]
                - durations: List of times in seconds. (list[float], each element: > 0) [Required]
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points in seconds. (float, 0.0002 to 1000). [Default: 1]
                - voltage_interval: Maximum voltage change between points in Volts. (float, 1e-4 to 1e-2). [Default: 0.001]
                - channels: List of channel numbers. [Required]
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]

        Returns:
            Dictionary containing the CP data (keyed by channel)
        """
        if params is None:
            params, kwargs = self._split_kwargs(kwargs)
        logger.info("Running CP test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.CP, params, **kwargs)

    @command
    def PEIS(
        self,
        params: dict[str, Any] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        Run PEIS (Potentiostatic Electrochemical Impedance Spectroscopy) test.

        Args:
            params: Dictionary containing:
                - voltage: Initial potential in Volts. (float, -10 to 10 V) [Required]
                - amplitude_voltage: Sinus amplitude in Volts (float, 1e-4 to 0.5 V). [Required]
                - initial_frequency: Initial frequency in Hertz (float, 10 µHz to 1 MHz). [Required]
                - final_frequency: Final frequency in Hertz (float, 10 µHz to 1 MHz). [Required]
                - frequency_number: Number of frequencies (int, 1 to 1000). [Required]
                - duration: Overall duration in seconds. (float, > 0) [Required]
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points in seconds. (float, 0.0002 to 1000 s). [Default: 1]
                - current_interval: Maximum time interval between points in Amps. (float, 1e-12 A to current_range A). [Default: 0.001]
                - sweep: Defines whether the spacing between frequencies is logarithmic ('log') or linear ('lin'). [Default: 'log']
                - repeat: Number of times to repeat the measurement and average the values for each frequency. (int, 1 to 10). [Default: 1]
                - correction: Drift correction. [Default: False]
                - wait: Adds a delay before the measurement at each frequency. The delay is expressed as a fraction of the period. (float, 0 to 5). [Default: 0]
                - channels: List of channel numbers. [Required]
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]

        Returns:
            Dict[str, List[List[float]]]: Channel-keyed measurement data.

            Data schema (PEIS):
                row = [frequency, Z_real, Z_imag, phase, flag]
                primary_x = "frequency"
                primary_y = "Z_real"

                Index | Name      | Unit | Meaning
                ------|-----------|------|-----------------------------------------
                0     | frequency | Hz   | Excitation frequency
                1     | Z_real    | Ω    | Real impedance component
                2     | Z_imag    | Ω    | Imaginary impedance component
                3     | phase     | rad  | Impedance phase angle
                4     | flag      | -    | Status/frequency-step boundary indicator
        """
        if params is None:
            params, kwargs = self._split_kwargs(kwargs)
        logger.info("Running PEIS test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.PEIS, params, **kwargs)

    @command
    def GEIS(
        self,
        params: dict[str, Any] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        Run GEIS (Galvanostatic Electrochemical Impedance Spectroscopy) test.

        Args:
            params: Dictionary containing:
                - current: Initial current in Ampere. (float, 1e-12 to current_range A) [Required]
                - amplitude_current: Sinus amplitude in Ampere. (float, 1e-9 to current_range A) [Required]
                - initial_frequency: Initial frequency in Hertz. (float, 10 µHz to 1 MHz) [Required]
                - final_frequency: Final frequency in Hertz. (float, 10 µHz to 1 MHz) [Required]
                - frequency_number: Number of frequencies. (int, 1 to 1000) [Required]
                - duration: Overall duration in seconds. (float, > 0) [Required]
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points in seconds. (float, 0.0002 to 1000 s). [Default: 1]
                - potential_interval: Maximum interval between points in Volts. [Default: 0.001]
                - sweep: Defines whether the spacing between frequencies is logarithmic ('log') or linear ('lin'). [Default: 'log']
                - repeat: Number of times to repeat the measurement and average the values for each frequency. (int, 1 to 10). [Default: 1]
                - correction: Drift correction. [Default: False]
                - wait: Adds a delay before the measurement at each frequency. The delay is expressed as a fraction of the period. (float, 0 to 5). [Default: 0]
                - channels: List of channel numbers. [Required]
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]

        Returns:
            Dict[str, List[List[float]]]: Channel-keyed measurement data.

            Data schema (GEIS):
                row = [frequency, Z_real, Z_imag, phase, flag]
                primary_x = "frequency"
                primary_y = "Z_real"

                Index | Name      | Unit | Meaning
                ------|-----------|------|-----------------------------------------
                0     | frequency | Hz   | Excitation frequency
                1     | Z_real    | Ω    | Real impedance component
                2     | Z_imag    | Ω    | Imaginary impedance component
                3     | phase     | rad  | Impedance phase angle
                4     | flag      | -    | Status/frequency-step boundary indicator
        """
        if params is None:
            params, kwargs = self._split_kwargs(kwargs)
        logger.info("Running GEIS test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.GEIS, params, **kwargs)

    @command
    def CV(
        self,
        params: dict[str, Any] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        Run CV (Cyclic Voltammetry) test.

        Args:
            params: Dictionary containing:
                - start: Start voltage. (float, -10 to 10 V). [Default: 0]
                - end: End voltage. Boundary voltage in forward scan. (float, -10 to 10 V). [Default: 0.5]
                - E2: Boundary voltage in backward scan. (float, -10 to 10 V). [Default: 0]
                - Ef: End voltage in the final cycle scan (float, -10 to 10 V). [Default: 0]
                - step: Voltage step. dEN/1000 (float, 1e-4 to 0.05 V). [Default: 0.01]
                - rate: Scan rate in V/s. (float, 1e-5 to 100 V/s). [Default: 0.01]
                - average: Average over points. (bool). [Default: False]
                - N_Cycles: Number of cycles. (int, 0 to 1000). [Default: 0]
                - voltage_range: Voltage range. Use ec_lib.ERange. Available: ERange.v2_5, ERange.v5, ERange.v10, ERange.AUTO. Can be provided as a string (e.g., "ERange.AUTO") which will be automatically converted. [Default: AUTO]
                - current_range: Current range. Use ec_lib.IRange. Available: IRange.p100 (±100 pA), IRange.n1 (±1 nA), IRange.u1 (±1 µA), IRange.m1 (±1 mA), IRange.m10 (±10 mA), IRange.a1 (±1 A), IRange.AUTO. Can be provided as a string (e.g., "IRange.m10") which will be automatically converted. [Default: AUTO]
                - channels: List of channel numbers. [Required]
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]

        Returns:
            Dict[str, List[List[float]]]: Channel-keyed measurement data.

            Data schema (CV):
                row = [potential, current, time, extra, flag]
                primary_x = "potential"
                primary_y = "current"

                Index | Name      | Unit | Meaning
                ------|-----------|------|-----------------------------------------
                0     | potential | V    | Working electrode potential
                1     | current   | A    | Measured current
                2     | time      | s    | Elapsed time
                3     | extra     | -    | Internal metadata/auxiliary value
                4     | flag      | -    | Status/cycle boundary indicator
        """
        if params is None:
            params, kwargs = self._split_kwargs(kwargs)
        logger.info("Running CV test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.CV, params, **kwargs)

    @command
    def MPP_Tracking(
        self,
        params: dict[str, Any] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        Run MPP_Tracking (Maximum Power Point Tracking) test.

        Args:
            params: Dictionary containing:
                - run_time: Run time in seconds. [Required]
                - init_vmpp: Initial v_mpp. [Required]
                - probe_step: Voltage step for probe. [Default: 0.005 V]
                - probe_points: Number of data points to collect for probe. [Default: 5]
                - probe_interval: How often to probe in seconds. [Default: 2]
                - record_interval: How often to record a data point in seconds. [Default: 1]
                - channels: List of channel numbers. [Required]
                - folder: Folder or file for saving data [Default: None]
                - by_channel: Save data by channel [Default: False]

        Returns:
            Dictionary containing the MPP_Tracking data (keyed by channel)
        """
        if params is None:
            params, kwargs = self._split_kwargs(kwargs)
        logger.info("Running MPP_Tracking test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.MPP_Tracking, params, **kwargs)

    @command
    def MPP(
        self,
        params: dict[str, Any] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        Run MPP (Maximum Power Point) test.

        Makes a CV scan and Voc scan and runs MPP tracking.

        Args:
            params: Dictionary containing:
                - run_time: Run time in seconds. [Required]
                - probe_step: Voltage step for probe. [Default: 0.005 V]
                - probe_points: Number of data points to collect for probe. [Default: 5]
                - probe_interval: How often to probe in seconds. [Default: 2]
                - record_interval: How often to record a data point in seconds. [Default: 1]
                - channels: List of channel numbers. [Required]
                - data: Data folder path. [Default: 'data']
                - by_channel: Save data by channel. [Default: False]
                - cv: Parameters passed to CV to find initial MPP, or {} for default. [Default: {}]

        Returns:
            Dictionary containing the MPP data (keyed by channel)
        """
        if params is None:
            params, kwargs = self._split_kwargs(kwargs)
        logger.info("Running MPP test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.MPP, params, **kwargs)

    @command
    def MPP_Cycles(
        self,
        params: dict[str, Any] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        Run MPP_Cycles (MPP tracking with periodic CV scans) test.

        Args:
            params: Dictionary containing:
                - run_time: Cycle run time in seconds. [Required]
                - cycles: Number of cycles to perform. [Required]
                - probe_step: Voltage step for probe. [Default: 0.01 V]
                - probe_points: Number of data points to collect for probe. [Default: 5]
                - probe_interval: How often to probe in seconds. [Default: 2]
                - record_interval: How often to record a data point in seconds. [Default: 1]
                - channels: List of channel numbers. [Required]
                - data: Data folder path. [Default: 'data']
                - by_channel: Save data by channel. [Default: False]
                - cv: Parameters for the CV. [Default: {}]

        Returns:
            Dictionary containing the MPP_Cycles data (keyed by channel)
        """
        if params is None:
            params, kwargs = self._split_kwargs(kwargs)
        logger.info("Running MPP_Cycles test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.MPP_Cycles, params, **kwargs)
