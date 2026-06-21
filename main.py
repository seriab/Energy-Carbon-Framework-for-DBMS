#!/usr/bin/env python3
import shlex, csv
import uuid
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from codecarbon import EmissionsTracker
from Functions import *
import sys
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

load_dotenv()

# Secrets from .env
co2_signal_api_token = os.getenv("CO2_SIGNAL_API_TOKEN")
pg_user = os.getenv("POSTGRES_USER")
pg_password = os.getenv("POSTGRES_PASSWORD")
mysql_user = os.getenv("MYSQL_USER")
mysql_password = os.getenv("MYSQL_PASSWORD")
redis_password = os.getenv("REDIS_PASSWORD")

# ===== Configuration =====
RUN_ECOFLOW_METER = True
RUN_SHELLY_METER = True

# mongodb,cassandra,postgres,mysql,redis
DBS_TO_RUN = ["mysql","redis","postgres","mongodb","cassandra"]   # Choose the DBs to run here
WORKLOADS  = ["workloada","workloadb","workloadc", "workloadd", "workloade", "workloadf"]
# WORKLOADS  = ["workloade"]
THREADS    = [2, 8, 16,32]
# THREADS    = [16]

HARDWARE_METRIC_FIELDS = [
    "hw_cpu_avg_percent", "hw_ram_avg_percent", "hw_cpu_temp_avg_c",
    "hw_cpu_peak_percent", "hw_ram_peak_percent", "hw_cpu_temp_peak_c",
    "hw_cpu_std_dev", "hw_cpu_saturation_time_percent",
    "hw_disk_read_total_mb", "hw_disk_write_total_mb",
    "hw_disk_read_throughput_mbps", "hw_disk_write_throughput_mbps",
    "hw_network_bytes_sent_total", "hw_network_bytes_recv_total",
    "hw_network_loopback_sent_total", "hw_network_loopback_recv_total"
]
OPERATIONS = ["READ", "UPDATE", "INSERT", "SCAN", "TOTAL"]
METRIC_FIELDS = ["ops", "count", "avg_us", "min_us", "max_us", "p95_us", "p99_us"]
REPEATS    = 20

RECORDCOUNT    = 1_000_000
OPERATIONCOUNT = 1_000_000
WORKLOAD_DIR   = "/opt/go-ycsb/workloads"

RESULTS_CSV = "results_energy_ycsb.csv"
LOG_DIR     = Path("logs")
HARDWARE_LOG_DIR = Path("meter_logs_hardware")
OUTPUT_DIR = Path("meter_logs_codecarbon")
LOG_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Parameters for the SCI calculation ---
TE_gCO2eq = 226.7 * 1000  # Total Embodied Emissions (gCO2e)
HARDWARE_LIFESPAN_YEARS = 4  # Hardware lifespan in years
RESOURCE_SHARE = 1.0  # Resource Share

# ===== Commands by engine =====
BINDINGS = {
    "mongodb": lambda W, T: f'''
go-ycsb run mongodb -P {WORKLOAD_DIR}/{W} \
  -p mongodb.url=mongodb://127.0.0.1:27017 \
  -p mongodb.db=ycsb -p mongodb.collection=ycsb \
  -p recordcount={RECORDCOUNT} -p operationcount={OPERATIONCOUNT} \
  -p requestdistribution=zipfian -p threadcount={T}
''',
    "cassandra": lambda W, T: f'''
go-ycsb run cassandra -P {WORKLOAD_DIR}/{W} \
  -p cassandra.host=127.0.0.1 -p cassandra.port=9042 \
  -p cassandra.keyspace=ycsb -p cassandra.readconsistency=one \
  -p cassandra.writeconsistency=one \
  -p recordcount={RECORDCOUNT} -p operationcount={OPERATIONCOUNT} \
  -p requestdistribution=zipfian -p threadcount={T}
''',
    "postgres": lambda W, T: f'''
go-ycsb run pg -P {WORKLOAD_DIR}/{W} \
  -p pg.host=127.0.0.1 -p pg.port=5432 \
  -p pg.user={pg_user} -p pg.password='{pg_password}' -p pg.db=ycsb \
  -p recordcount={RECORDCOUNT} -p operationcount={OPERATIONCOUNT} \
  -p requestdistribution=zipfian -p threadcount={T}
''',
    "mysql": lambda W, T: f'''
go-ycsb run mysql -P {WORKLOAD_DIR}/{W} \
  -p mysql.host=127.0.0.1 -p mysql.port=3306 \
  -p mysql.user={mysql_user} -p mysql.password='{mysql_password}' -p mysql.db=ycsb \
  -p recordcount={RECORDCOUNT} -p operationcount={OPERATIONCOUNT} \
  -p requestdistribution=zipfian -p threadcount={T}
''',
    "redis": lambda W, T: f'''
go-ycsb run redis -P {WORKLOAD_DIR}/{W} \
  -p redis.host=127.0.0.1 -p redis.port=6379 \
  -p redis.password='{redis_password}' -p redis.db=0 \
  -p recordcount={RECORDCOUNT} -p operationcount={OPERATIONCOUNT} \
  -p requestdistribution=zipfian -p threadcount={T}
'''
}

# ===== Executor =====
def run_one(db, workload, threads, run_id):
    manage_db_services(db)
    cmd = " ".join(BINDINGS[db](workload, threads).split())
    start_ts = datetime.utcnow().isoformat()
    guid= str(uuid.uuid4())
    log_path = LOG_DIR / f"{db}_{workload}_t{threads}_t{guid}_run{run_id}.log"


    tracker = EmissionsTracker(output_dir=str(OUTPUT_DIR), tracking_mode="machine",force_ram_power = 10,
    co2_signal_api_token = co2_signal_api_token)

    if RUN_ECOFLOW_METER:
        ecoflow_command = f'python MeterEcoflow.py {guid}'
        ecoflow_process = subprocess.Popen(ecoflow_command, shell=True)

    hardware_command = f'python MeterHardware.py {guid}'
    hardware_process = subprocess.Popen(hardware_command, shell=True)

    if RUN_SHELLY_METER:
        shelly_command   = f'python MeterShelly.py {guid}'
        shelly_process = subprocess.Popen(shelly_command, shell=True)


    tracker.start()
    t0 = time.time()
    proc = subprocess.run(
        shlex.split(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    duration = time.time() - t0

    if RUN_ECOFLOW_METER:
        ecoflow_command = "pkill -f MeterEcoflow"
        ecoflow_process = subprocess.Popen(ecoflow_command, shell=True)

    hardware_command = "pkill -f MeterHardware"
    hardware_process = subprocess.Popen(hardware_command, shell=True)

    if RUN_SHELLY_METER:
        shelly_command =  "pkill -f MeterShelly"
        shelly_process = subprocess.Popen(shelly_command, shell=True)

    emissions_kg = tracker.stop()



    print("### Ecoflow Smart Plug Metrics ###")
    if RUN_ECOFLOW_METER:
        energy_consumed_ecoflow, enddate_ecoflow, duration_ecoflow = calculate_ecoflow_consumption(f"meter_logs_ecoflow/ecoflow_data_{guid}.csv",
        overwrite_file=True)
        print(f'Ecoflow energy consumed: {energy_consumed_ecoflow} kWh')
        print(f'Ecoflow completion date: {enddate_ecoflow}')
        print(f'Ecoflow duration: {duration_ecoflow} s')
    else:
        energy_consumed_ecoflow = 0
        print(f'Ecoflow energy consumed: {energy_consumed_ecoflow} kWh')


    log_path.write_text(proc.stdout)
    perf = parse_metrics(proc.stdout)
    data = tracker.final_emissions_data

    print("### Shelly Plug S Gen3 Metrics ###")
    if RUN_SHELLY_METER:
        energy_consumed_shelly, enddate_shelly, duration_shelly = analyze_shelly_consumption(f"meter_logs_shelly/shelly_data_{guid}.csv",
        overwrite_file=True)
        print(f'Shelly energy consumed: {energy_consumed_shelly} kWh')
        print(f'Shelly completion date: {enddate_shelly}')
        print(f'Shelly duration: {duration_shelly} s')
    else:
        energy_consumed_shelly = 0
        print(f'Shelly energy consumed: {energy_consumed_shelly} kWh')

    print("### Codecarbon Metrics ###")
    print(f'Codecarbon energy consumed: {data.energy_consumed} kWh')
    print(f'Completion timestamp: {data.timestamp}')
    print(f'Codecarbon emissions (kgCO2e): {data.emissions} kgCO2e')
    print(f'Codecarbon emissions (gCO2e): {data.emissions*1000} gCO2e')
    print(f'Codecarbon duration: {data.duration} s')

    print("### YCSB Metrics ###")

    total_count = perf.get("TOTAL", {}).get("count", 0)  # Functional unit
    throughput_ops = perf.get("TOTAL", {}).get("ops", 0)  # Throughput

    print(f'Total operations executed (Count): {total_count}')
    print(f'Throughput: {throughput_ops} ops/s')



    print("### Hardware Metrics ###")
    hardware_metrics = analyze_hardware_consumption(f"meter_logs_hardware/hardware_data_{guid}.csv")
    if hardware_metrics:
        # Print all hardware values
        print(f'Average CPU: {hardware_metrics["hw_cpu_avg_percent"]} %')
        print(f'Peak CPU: {hardware_metrics["hw_cpu_peak_percent"]} %')
        print(f'Average RAM: {hardware_metrics["hw_ram_avg_percent"]} %')
        print(f'Peak RAM: {hardware_metrics["hw_ram_peak_percent"]} %')
        print(f'Average Temperature: {hardware_metrics["hw_cpu_temp_avg_c"]} °C')
        print(f'Peak Temperature: {hardware_metrics["hw_cpu_temp_peak_c"]} °C')
        print(f'CPU_percent standard deviation: {hardware_metrics["hw_cpu_std_dev"]}')
        print(f'CPU saturation time: {hardware_metrics["hw_cpu_saturation_time_percent"]} %')
        print(f'Total disk read: {hardware_metrics["hw_disk_read_total_mb"]} MB')
        print(f'Total disk write: {hardware_metrics["hw_disk_write_total_mb"]} MB')
        print(f'Disk read throughput: {hardware_metrics["hw_disk_read_throughput_mbps"]} MB/s')
        print(f'Disk write throughput: {hardware_metrics["hw_disk_write_throughput_mbps"]} MB/s')
        print(f'Network bytes sent: {hardware_metrics.get("hw_network_bytes_sent_total", "N/A")}')
        print(f'Network bytes received: {hardware_metrics.get("hw_network_bytes_recv_total", "N/A")}')
        print(f'-- Network (Loopback) bytes sent: {hardware_metrics.get("hw_network_loopback_sent_total", "N/A")}')
        print(f'-- Network (Loopback) bytes received: {hardware_metrics.get("hw_network_loopback_recv_total", "N/A")}')
    else:
        print("Could not calculate hardware metrics.")


    print("### SCI Metrics ###")
    # Calculate SCI
    sci_results = calculate_sci(
        duration_s=data.duration,
        emissions_kg=data.emissions,
        energy_kwh=data.energy_consumed,
        total_ops= total_count,
        total_embodied_emissions_g=TE_gCO2eq,
        hardware_lifespan_years=HARDWARE_LIFESPAN_YEARS,
        resource_share=RESOURCE_SHARE)

    sci_m_gco2e = sci_results["sci_m_gco2e"]
    sci_o_gco2e = sci_results["sci_o_gco2e"]
    sci_i_gco2e_per_kwh = sci_results["sci_i_gco2e_per_kwh"]
    time_share = sci_results["sci_time_share"]
    sci_score = sci_results["sci_score"]


    print(f'E: {data.energy_consumed} kWh')
    print(f'M: {sci_m_gco2e} gCO2e')
    print(f'I: {sci_i_gco2e_per_kwh} gCO2e/kWh')
    print(f'O: {sci_o_gco2e} gCO2e')
    print(f'TS: {time_share}')
    print(f'SCI Score: {sci_score} gCO2e/op')

    sanitized_cmd = cmd
    if pg_password:
        sanitized_cmd = sanitized_cmd.replace(f"'{pg_password}'", "'****'")
    if mysql_password:
        sanitized_cmd = sanitized_cmd.replace(f"'{mysql_password}'", "'****'")
    if redis_password:
        sanitized_cmd = sanitized_cmd.replace(f"'{redis_password}'", "'****'")


    row = {
        "timestamp_utc": start_ts,
        "db": db,
        "workload": workload,
        "threads": threads,
        "run": run_id,
        "duration_s": duration,
        "cc_energy_kwh": data.energy_consumed,
        "cc_emissions_kg": data.emissions_kg,
        "cc_cpu_energy_kwh": data.cpu_energy,
        "cc_ram_energy_kwh": data.ram_energy,
        "cc_gpu_energy_kwh": getattr(data, "gpu_energy", 0.0),
        "cc_run_id": data.run_id,
        "cc_experiment_id": data.experiment_id,
        "guid_global":guid,
        "energy_consumed_ecoflow":energy_consumed_ecoflow,
        "energy_consumed_shelly":energy_consumed_shelly,
        "sci_m_gco2e":sci_m_gco2e,
        "sci_o_gco2e":sci_o_gco2e,
        "sci_i_gco2e_per_kwh":sci_i_gco2e_per_kwh,
        "time_share":time_share,
        "sci_score":sci_score,
        "log_file": str(log_path),
        "cmd": sanitized_cmd,
    }


    # Flatten all operations returned by YCSB, including TOTAL if present
    for op, m in perf.items():
        op_name = op.upper()
        if op_name not in OPERATIONS:
            continue
        for metric in METRIC_FIELDS:
            # e.g. row["READ_avg_us"] = m["avg_us"]
            row[f"{op_name}_{metric}"] = m.get(metric)

    # Add hardware metrics to the result if they exist
    if hardware_metrics:
        row.update(hardware_metrics)

    return row

# ===== Main =====
def main():
    check_sudo_nopasswd()
    base_fieldnames = [
        "timestamp_utc","db","workload","threads","run","duration_s",
        "cc_energy_kwh","cc_emissions_kg","cc_cpu_energy_kwh","cc_ram_energy_kwh","cc_gpu_energy_kwh", "cc_run_id",
        "cc_experiment_id", "guid_global","energy_consumed_ecoflow","energy_consumed_shelly" ,"sci_m_gco2e", "sci_o_gco2e",
        "sci_i_gco2e_per_kwh", "time_share", "sci_score"
    ]
    perf_fieldnames = [f"{op}_{metric}" for op in OPERATIONS for metric in METRIC_FIELDS] + HARDWARE_METRIC_FIELDS
    final_fieldnames = ["log_file", "cmd"]
    fieldnames = base_fieldnames + perf_fieldnames + final_fieldnames

    new_file = not Path(RESULTS_CSV).exists()
    with open(RESULTS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval=None)
        if new_file:
            writer.writeheader()
        try:
            for db in DBS_TO_RUN:
                if db not in BINDINGS:
                    raise ValueError(f"DB '{db}' is not in {list(BINDINGS.keys())}")
                for workload in WORKLOADS:
                    for threads in THREADS:
                        for run_id in range(1, REPEATS + 1):
                            print(f">>> {db} {workload} threads={threads} run={run_id}")
                            row = run_one(db, workload, threads, run_id)
                            # DictWriter with restval=None handles filling in missing fields.
                            writer.writerow(row)
                            f.flush()
                            print("Waiting 3 seconds for the next experiment...")
                            time.sleep(3)
        finally:
            stop_all_db_services()

if __name__ == "__main__":
    main()
