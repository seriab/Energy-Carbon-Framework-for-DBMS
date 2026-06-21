import csv
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
import typing
import pandas as pd
from codecarbon import EmissionsTracker
from pathlib import Path

# Unit conversion constant to improve readability.
WATT_SECONDS_PER_KWH = 3600000.0

DB_SERVICE_NAMES = {
    "mongodb": "mongod",
    "cassandra": "cassandra",
    "postgres": "postgresql-17.service",
    "mysql": "mariadb",
    "mariadb": "mariadb",
    "redis": "redis",
}

# ===== Metrics parser =====
OPS_RE = re.compile(
    r"([A-Z_]+)\s*-\s*Takes\(s\):\s*([\d\.]+).*?Count:\s*(\d+)"
    r".*?OPS:\s*([\d\.]+).*?Avg\(us\):\s*([\d\.]+).*?Min\(us\):\s*([\d\.]+)"
    r".*?Max\(us\):\s*([\d\.]+).*?95th\(us\):\s*([\d\.]+).*?99th\(us\):\s*([\d\.]+)",
    re.I | re.DOTALL
)

def parse_metrics(text: str):
    # go-ycsb prints intermediate statistics. We are only interested in the final block.
    # The final block always appears after "Run finished".
    summary_part = text.split("Run finished")[-1]

    ops_blocks = OPS_RE.findall(summary_part)
    latest = {}
    for op, takes, count, ops, avg_us, min_us, max_us, p95_us, p99_us in ops_blocks:
        latest[op.upper()] = {
            "takes_s": float(takes),
            "count": int(count),
            "ops": float(ops),
            "avg_us": float(avg_us),
            "min_us": float(min_us),
            "max_us": float(max_us),
            "p95_us": float(p95_us),
            "p99_us": float(p99_us),
        }
    return latest

def check_sudo_nopasswd():
    """Checks if sudo can be run without a password. Exits if not."""
    print("--- Checking for passwordless sudo ---")
    proc = subprocess.run("sudo -n true", shell=True, capture_output=True)
    if proc.returncode != 0:
        print("ERROR: sudo requires a password.")
        print("This script needs to be run by a user with passwordless sudo privileges.")
        print("Please configure /etc/sudoers or run the script with a user that has these privileges.")
        print("Exiting.")
        sys.exit(1)
    print("--- Sudo check passed ---")

def manage_db_services(db_to_start: str):
    """Stops all other DB services and starts the specified one intelligently."""
    if db_to_start not in DB_SERVICE_NAMES:
        print(f"Warning: DB '{db_to_start}' not found in DB_SERVICE_NAMES. No service management will be performed.")
        return

    service_to_start = DB_SERVICE_NAMES[db_to_start]

    # Stop other services
    for db, service_name in DB_SERVICE_NAMES.items():
        if db != db_to_start:
            # Check if service is active before trying to stop it
            status_proc = subprocess.run(f"systemctl is-active --quiet {service_name}", shell=True)
            if status_proc.returncode == 0: # Service is active
                print(f"Stopping {db} ({service_name})...")
                stop_proc = subprocess.run(f"sudo systemctl stop {service_name}", shell=True, capture_output=True, text=True)
                if stop_proc.returncode != 0:
                    print(f"Warning: Failed to stop service {service_name}. Stderr: {stop_proc.stderr}")

    # Start the required service if not already running
    print(f"Checking status of {db_to_start} ({service_to_start})...")
    status_proc = subprocess.run(f"systemctl is-active --quiet {service_to_start}", shell=True)
    if status_proc.returncode == 0:
        print(f"Service {service_to_start} is already active.")
    else:
        print(f"Service {service_to_start} is not running. Starting it...")
        start_proc = subprocess.run(f"sudo systemctl start {service_to_start}", shell=True, capture_output=True, text=True)
        if start_proc.returncode != 0:
            raise Exception(f"Failed to start service {service_to_start}: {start_proc.stderr}")
        print(f"Service {service_to_start} started. Waiting 10 seconds for initialization...")
        time.sleep(10)

def stop_all_db_services():
    """Stops all DB services."""
    print("--- Stopping all database services ---")
    for db, service_name in DB_SERVICE_NAMES.items():
        status_proc = subprocess.run(f"systemctl is-active --quiet {service_name}", shell=True)
        if status_proc.returncode == 0: # Service is active
            print(f"Stopping {db} ({service_name})...")
            stop_proc = subprocess.run(f"sudo systemctl stop {service_name}", shell=True, capture_output=True, text=True)
            if stop_proc.returncode != 0:
                print(f"Warning: Failed to stop service {service_name}. Stderr: {stop_proc.stderr}")
    print("--- All database services stopped ---")

def calculate_ecoflow_consumption(file_path: str, overwrite_file: bool = False) -> typing.Tuple[float, typing.Union[str, None], int]:
    """
    Calculates power consumption from an EcoFlow CSV file,
    interpolating the data to fill in gaps.

    This function reads the specified CSV file, fills in any potential
    gaps in the data using linear interpolation for watts and
    forward fill for other data. Then, it calculates the total energy.
    Optionally, it can overwrite the original file with the
    interpolated data.

    Args:
        file_path: The path to the EcoFlow CSV file to process.
        overwrite_file: If True, overwrites the input file with the
                        interpolated data marked as synthetic.

    Returns:
        A tuple containing (total_kwh, enddate, final_duration_seconds).
    """
    data_path = Path(file_path)

    if not data_path.is_file():
        print(f"Warning: File '{data_path}' was not found.")
        return 0.0, None, 0

    try:
        df = pd.read_csv(data_path)
    except pd.errors.EmptyDataError:
        print(f"Warning: File '{data_path}' is empty.")
        return 0.0, None, 0

    if df.empty:
        return 0.0, None, 0

    # Save the original order of the columns for the output file
    # If 'is_synthetic' already exists, we do not add it again.
    original_cols = df.columns.tolist()
    if 'is_synthetic' in original_cols:
        original_cols.remove('is_synthetic')

    # --- 1. Fill gaps in time (Interpolation) ---

    # Convert 'datenow' to datetime to be able to operate with time
    df['datenow'] = pd.to_datetime(df['datenow'], format='%Y-%m-%dT%H:%M:%S')
    # Ensure 'watts' is numeric to be able to interpolate
    df['watts'] = pd.to_numeric(df['watts'], errors='coerce')

    # Determine the most common time interval (should be 1 second)
    time_diffs = df['datenow'].diff().value_counts()
    time_step = pd.Timedelta(seconds=1)  # Assume 1s by default if there is not enough data
    if not time_diffs.empty:
        time_step = time_diffs.index[0]

    # Generate a complete time range from start to end
    start_time = df['datenow'].min()
    end_time = df['datenow'].max()
    complete_times = pd.date_range(start=start_time, end=end_time, freq=time_step)

    # Reindex the DataFrame to match the complete time range,
    # creating NaN rows where data is missing.
    df_reindexed = df.set_index('datenow').reindex(complete_times)

    # Mark the rows that have been added. Done before filling NaNs.
    # Any original column (like 'run_id') will be NaN in the new rows.
    df_reindexed['is_synthetic'] = df_reindexed['run_id'].isnull()

    # Interpolate 'watts' values (lineally by default)
    df_reindexed['watts'] = df_reindexed['watts'].interpolate()

    # Forward fill the rest of the columns with the last valid value
    df_reindexed = df_reindexed.ffill()

    # Reset the index so 'datenow' becomes a column again
    df_interpolated = df_reindexed.reset_index().rename(columns={'index': 'datenow'})

    # The original duration may have jumps. We recalculate it to be sequential.
    df_interpolated['duration'] = range(len(df_interpolated))

    # --- 2. Calculate consumption ---
    # The Shelly logic is `power * delta_time`.
    # After interpolating, our delta_time is constant (1 second).
    # Therefore, the total energy in Watt-seconds (Joules) is the sum of the watts.
    total_energy_ws = df_interpolated['watts'].sum()

    # Convert total energy from Ws to kWh
    total_energy_kwh = total_energy_ws / WATT_SECONDS_PER_KWH

    # Get the final date and duration of the already processed DataFrame
    last_row = df_interpolated.iloc[-1]
    enddate = last_row['datenow'].strftime('%Y-%m-%dT%H:%M:%S')
    duration = int(last_row['duration'])

    # --- 3. Save the interpolated file (optional) ---
    if overwrite_file:
        # The output path is the same as the input path
        output_path = data_path

        # Prepare the DataFrame to save
        df_to_save = df_interpolated.copy()
        # Convert 'datenow' back to string with the desired format
        df_to_save['datenow'] = df_to_save['datenow'].dt.strftime('%Y-%m-%dT%H:%M:%S')

        # Reorder the columns to match the original + the new one
        final_cols = original_cols + ['is_synthetic']
        final_cols = [c for c in final_cols if c in df_to_save.columns]
        df_to_save = df_to_save[final_cols]

        df_to_save.to_csv(output_path, index=False, float_format='%.1f')
        print(f"Input file overwritten with interpolated data: {output_path}")

    return total_energy_kwh, enddate, duration

def calculate_sci(
    duration_s: float,
    emissions_kg: float,
    energy_kwh: float,
    total_ops: float,
    total_embodied_emissions_g: float = 226.7 * 1000,
    hardware_lifespan_years: int = 4,
    resource_share: float = 1.0,
) -> typing.Dict:
    """
    Calculates the SCI (Software Carbon Intensity) metric and its components.

    Args:
        duration_s: The duration of the experiment in seconds.
        emissions_kg: The operational emissions in kg CO2e of the experiment.
        energy_kwh: The energy consumption in kWh of the experiment.
        total_ops: The total number of operations (functional unit) of the experiment.
        total_embodied_emissions_g: Total embodied hardware emissions in gCO2e.
        hardware_lifespan_years: Expected hardware lifespan in years.
        resource_share: Proportion of system resources dedicated to the test (0.0 to 1.0).

    Returns:
        A dictionary with the SCI components and the final score.
    """
    # --- M: Embodied Emissions ---
    hardware_lifespan_hours = hardware_lifespan_years * 365 * 24
    duration_hours = duration_s / 3600
    time_share = duration_hours / hardware_lifespan_hours
    sci_m_gco2e = total_embodied_emissions_g * time_share * resource_share

    # --- O: Operational Emissions ---
    sci_o_gco2e = emissions_kg * 1000

    # --- I: Carbon Intensity ---
    # Explicitly calculated for logging/recording.
    sci_i_gco2e_per_kwh = sci_o_gco2e / energy_kwh if energy_kwh > 0 else None

    # --- SCI Score: (O + M) / R ---
    sci_score = (sci_o_gco2e + sci_m_gco2e) / total_ops if total_ops > 0 else None

    return {
        "sci_m_gco2e": sci_m_gco2e,
        "sci_o_gco2e": sci_o_gco2e,
        "sci_i_gco2e_per_kwh": sci_i_gco2e_per_kwh,
        "sci_time_share": time_share,
        "sci_score": sci_score,
    }

def analyze_shelly_consumption(file_path: str, overwrite_file: bool = False) -> typing.Tuple[float, typing.Union[str, None], int]:
    """
    Calculates power consumption from a Shelly CSV file,
    interpolating the data to fill in gaps.

    This function reads the specified CSV file, fills in any potential
    gaps in the data using linear interpolation for watts and
    forward fill for other data. Then, it calculates the total energy.
    Optionally, it can overwrite the original file with the
    interpolated data.

    Args:
        file_path: The path to the input CSV file.
        overwrite_file: If True, overwrites the input file with the
                        interpolated data marked as synthetic.

    Returns:
        A tuple containing (total_kwh, enddate, final_duration_seconds).
    """
    data_path = Path(file_path)

    if not data_path.is_file():
        print(f"Warning: File '{data_path}' was not found.")
        return 0.0, None, 0

    try:
        df = pd.read_csv(data_path)
    except pd.errors.EmptyDataError:
        print(f"Warning: File '{data_path}' is empty.")
        return 0.0, None, 0

    if df.empty:
        return 0.0, None, 0

    original_cols = df.columns.tolist()
    if 'is_synthetic' in original_cols:
        original_cols.remove('is_synthetic')

    df['datenow'] = pd.to_datetime(df['datenow'], format='%Y-%m-%dT%H:%M:%S')
    df['watts'] = pd.to_numeric(df['watts'], errors='coerce')

    time_diffs = df['datenow'].diff().value_counts()
    time_step = pd.Timedelta(seconds=1)
    if not time_diffs.empty:
        time_step = time_diffs.index[0]

    start_time = df['datenow'].min()
    end_time = df['datenow'].max()
    complete_times = pd.date_range(start=start_time, end=end_time, freq=time_step)

    df_reindexed = df.set_index('datenow').reindex(complete_times)
    df_reindexed['is_synthetic'] = df_reindexed['run_id'].isnull()
    df_reindexed['watts'] = df_reindexed['watts'].interpolate()
    df_reindexed = df_reindexed.ffill()
    df_interpolated = df_reindexed.reset_index().rename(columns={'index': 'datenow'})
    df_interpolated['duration'] = range(len(df_interpolated))

    total_energy_ws = df_interpolated['watts'].sum()
    total_energy_kwh = total_energy_ws / WATT_SECONDS_PER_KWH

    last_row = df_interpolated.iloc[-1]
    enddate = last_row['datenow'].strftime('%Y-%m-%dT%H:%M:%S')
    duration = int(last_row['duration'])

    if overwrite_file:
        output_path = data_path
        df_to_save = df_interpolated.copy()
        df_to_save['datenow'] = df_to_save['datenow'].dt.strftime('%Y-%m-%dT%H:%M:%S')
        final_cols = original_cols + ['is_synthetic']
        final_cols = [c for c in final_cols if c in df_to_save.columns]
        df_to_save = df_to_save[final_cols]
        df_to_save.to_csv(output_path, index=False, float_format='%.2f') # Shelly usually has 2 decimals
        print(f"Input file overwritten with interpolated data: {output_path}")

    return total_energy_kwh, enddate, duration

def analyze_hardware_consumption(file_path: str) -> typing.Optional[dict]:
    """
    Analyzes a hardware metrics CSV file and calculates key statistics.

    Calculates averages, peaks, standard deviation, and I/O performance for
    CPU, RAM, Temperature, and Disk metrics.

    Args:
        file_path: The path to the hardware CSV file to process.

    Returns:
        A dictionary with the calculated metrics or None if the file cannot be processed.
    """
    data_path = Path(file_path)
    if not data_path.is_file():
        print(f"Warning: Hardware file not found at '{data_path}'")
        return None

    try:
        df = pd.read_csv(data_path)
        if df.shape[0] < 2:
            print(f"Warning: The hardware file '{data_path}' does not have enough data for analysis.")
            return None
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: The hardware file '{data_path}' is empty or was not found.")
        return None

    # --- 1. Prepare the data ---
    # Convert columns to numeric, forcing errors to NaN
    for col in df.columns:
        if col not in ['global_run_id', 'Time']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Calculate total sampling duration
    df['Time'] = pd.to_datetime(df['Time'], format='%Y-%m-%d_%H:%M:%S')
    duration_s = (df['Time'].iloc[-1] - df['Time'].iloc[0]).total_seconds()
    if duration_s <= 0:
        duration_s = 1 # Avoid division by zero if duration is null or negative

    # --- 2. Calculate Metrics ---
    metrics = {}

    # Typical Load (Averages)
    metrics['hw_cpu_avg_percent'] = df['CPU_percent'].mean()
    metrics['hw_ram_avg_percent'] = df['RAM_percent'].mean()
    metrics['hw_cpu_temp_avg_c'] = df['CPU_Temp_C'].mean()

    # Stress Points (Peaks)
    metrics['hw_cpu_peak_percent'] = df['CPU_percent'].max()
    metrics['hw_ram_peak_percent'] = df['RAM_percent'].max()
    metrics['hw_cpu_temp_peak_c'] = df['CPU_Temp_C'].max()

    # Stability (Standard Deviation)
    metrics['hw_cpu_std_dev'] = df['CPU_percent'].std()

    # CPU Saturation Time (>75%)
    saturated_time = df[df['CPU_percent'] > 75].shape[0]
    metrics['hw_cpu_saturation_time_percent'] = (saturated_time / df.shape[0]) * 100 if df.shape[0] > 0 else 0

    # I/O Performance (Throughput)
    bytes_to_mb = 1 / (1024 * 1024)
    total_disk_read_mb = (df['Disk_Read_B'].iloc[-1] - df['Disk_Read_B'].iloc[0]) * bytes_to_mb
    total_disk_write_mb = (df['Disk_Write_B'].iloc[-1] - df['Disk_Write_B'].iloc[0]) * bytes_to_mb

    metrics['hw_disk_read_total_mb'] = total_disk_read_mb
    metrics['hw_disk_write_total_mb'] = total_disk_write_mb
    metrics['hw_disk_read_throughput_mbps'] = total_disk_read_mb / duration_s
    metrics['hw_disk_write_throughput_mbps'] = total_disk_write_mb / duration_s

    # Network Performance (Total)
    # Columns are assumed to exist. Error handling added in case they do not.
    if 'Net_Sent_B' in df.columns and 'Net_Recv_B' in df.columns:
        metrics['hw_network_bytes_sent_total'] = df['Net_Sent_B'].iloc[-1] - df['Net_Sent_B'].iloc[0]
        metrics['hw_network_bytes_recv_total'] = df['Net_Recv_B'].iloc[-1] - df['Net_Recv_B'].iloc[0]

    if 'Net_Loopback_Sent_B' in df.columns and 'Net_Loopback_Recv_B' in df.columns:
        metrics['hw_network_loopback_sent_total'] = df['Net_Loopback_Sent_B'].iloc[-1] - df['Net_Loopback_Sent_B'].iloc[0]
        metrics['hw_network_loopback_recv_total'] = df['Net_Loopback_Recv_B'].iloc[-1] - df['Net_Loopback_Recv_B'].iloc[0]

    # Round all values for a cleaner output
    for key, value in metrics.items():
        metrics[key] = round(value, 4) if isinstance(value, float) else value

    return metrics
