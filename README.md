# An Energy–Carbon Measurement Framework for Sustainable Database Systems

A comprehensive profiling framework designed to benchmark database management systems (DBMS) using the **Yahoo! Cloud Serving Benchmark (YCSB)** while tracking system resource usage, power consumption, and carbon emissions.

The framework supports multiple measurement inputs, including software estimation (CodeCarbon) and physical smart plugs (Shelly), calculating the **Software Carbon Intensity (SCI)** metric for comparison.

---

## Features

- **Multi-Database Support**: Runs benchmarks on MongoDB, Cassandra, PostgreSQL, MySQL, and Redis.
- **Service Lifecycle Management**: Automatically manages database service lifecycles (stops inactive databases and starts/initializes the target database).
- **Dual-Source Power Tracking**:
  - **CodeCarbon**: Estimates energy usage at the software level.
  - **Shelly Plug S Gen3**: Queries consumption locally via HTTP RPC request.
- **Hardware Telemetry**: Monitors CPU usage/temperature, RAM, Swap, Disk read/write rates, and Network throughput (including local loopback isolation).
- **SCI Score Computation**: Calculates the Software Carbon Intensity score ($SCI = \frac{O + M}{R}$) based on operational emissions ($O$), embodied hardware emissions ($M$), and functional unit operations ($R$).

---

## Architecture & Project Structure

- **[main.py](./main.py)**: The main orchestrator. It manages the benchmark loops (combinations of databases, workloads, threads, and repeats), controls database services, and spawns/stops measurement processes.
- **[Functions.py](./Functions.py)**: Contains utility functions for data parsing, database service management, smart plug data interpolation, and SCI score calculation.
- **[MeterShelly.py](./MeterShelly.py)**: Standalone script that polls a local Shelly Plug S Gen3 via HTTP POST RPC.
- **[MeterHardware.py](./MeterHardware.py)**: Standalone script tracking system-level telemetry using `psutil`.

---

## Prerequisites & Requirements

### 1. Operating System & Permissions
- **Linux** (configured with `systemd` to manage DB services. Verified on Rocky Linux 9.4).

### 2. Database Services
Ensure you have the following services installed and configured under systemctl with the names:
- MongoDB v6.0.26 (`mongod`)
- Cassandra v4.1.9 (`cassandra`)
- PostgreSQL v17.6 (`postgresql-17.service`)
- MySQL/MariaDB (MariaDB v10.5.27) (`mariadb`)
- Redis v6.2.19 (`redis`)

### 3. Go-YCSB
- **go-ycsb** v1.0.1 must be installed on your system.
- Workloads directory path: `/opt/go-ycsb/workloads` (contains `workloada`, `workloadb`, etc.).

---

## Installation & Setup

1. **Install Python dependencies**:
   ```bash
   pip install pandas codecarbon python-dotenv psutil requests
   ```

2. **Configure Environment Variables**:
   Create a `.env` file in the root directory (based on the template below):
   ```env
   # CO2 Signal API Token (used by CodeCarbon)
   CO2_SIGNAL_API_TOKEN=your_co2_signal_token

   # Database Credentials
   POSTGRES_USER=ycsb
   POSTGRES_PASSWORD=your_postgres_password
   MYSQL_USER=ycsb
   MYSQL_PASSWORD=your_mysql_password
   REDIS_PASSWORD=your_redis_password
   ```

3. **Configure Shelly Smart Plug IP**:
   Modify the default IP inside [MeterShelly.py](./MeterShelly.py) (`SHELLY_IP = "192.168.1.136"`) or specify it dynamically if running manually.

---

## Configuration & Usage

### Benchmark Execution Settings
   You can customize the benchmark matrix inside the `# ===== Configuration =====` section of [main.py](./main.py):
- `RUN_SHELLY_METER`: Set to `True` / `False` to enable/disable Shelly plug logging.
- `DBS_TO_RUN`: List of databases to cycle through (`mysql`, `redis`, `postgres`, `mongodb`, `cassandra`).
- `WORKLOADS`: Workloads to run (e.g., `workloada` to `workloadf`).
- `THREADS`: List of threads configuration to test (e.g. `[2, 8, 16, 32]`).
- `REPEATS`: Number of runs per configuration (default: `15`).
- `RECORDCOUNT` & `OPERATIONCOUNT`: Default is set to `1_000_000` (1 million records and 1 million operations per run).

### Running the Benchmark
Execute the framework from your terminal:
```bash
sudo python main.py
```
> **Note**: Sudo is required to allow the script to stop/start database services via `systemctl` and read hardware sensor temperatures.

---

## Outputs & Log Files

All outputs are saved relative to the project directory:
- **`results_energy_ycsb.csv`**: Contains the aggregated results of all runs. This CSV contains general benchmark information (duration, database, workload, threads), CodeCarbon estimations, Smart Plug outputs, calculated SCI scores, and average hardware telemetry metrics (CPU/RAM/Temp/IO).
- **`logs/`**: Raw benchmark outputs and logs of individual YCSB runs.
- **`meter_logs_shelly/`**: CSV time-series files from the Shelly plug.
- **`meter_logs_hardware/`**: CSV time-series files from the hardware monitoring system.
- **`meter_logs_codecarbon/`**: CodeCarbon output logs.
