import psutil
import time
import csv
import sys
from datetime import datetime
from pathlib import Path

def get_system_metrics(global_run_id):
    # CPU metrics
    cpu_total = psutil.cpu_percent(interval=None)  # Total CPU usage
    cpu_times = psutil.cpu_times_percent(interval=None)
    cpu_user = cpu_times.user  # CPU usage in user mode
    cpu_system = cpu_times.system  # CPU usage in system mode
    try:
        sensors = psutil.sensors_temperatures()
        cpu_temp = sensors['coretemp'][0].current  # CPU temperature (Celsius)
    except (KeyError, AttributeError):
        cpu_temp = "N/A"

    # Memory metrics
    memory_info = psutil.virtual_memory()
    memory_used_percent = memory_info.percent  # RAM usage (%)
    swap_info = psutil.swap_memory()
    swap_used_percent = swap_info.percent  # Swap usage (%)

    # Disk metrics
    disk_io = psutil.disk_io_counters()
    disk_read = disk_io.read_bytes  # Disk read (bytes)
    disk_write = disk_io.write_bytes  # Disk write (bytes)
    disk_read_time = disk_io.read_time  # Disk read time (ms)
    disk_write_time = disk_io.write_time  # Disk write time (ms)

    # Network metrics
    net_io = psutil.net_io_counters()
    bytes_sent = net_io.bytes_sent  # Bytes sent over network
    bytes_received = net_io.bytes_recv  # Bytes received over network

    # Get loopback interface stats specifically to isolate internal traffic
    net_io_per_nic = psutil.net_io_counters(pernic=True)
    loopback_sent = 0
    loopback_recv = 0
    # Interface name is 'lo' on Linux, might be different on other OS
    if 'lo' in net_io_per_nic:
        loopback_sent = net_io_per_nic['lo'].bytes_sent
        loopback_recv = net_io_per_nic['lo'].bytes_recv

    return {
        'global_run_id': global_run_id,
        'Time': datetime.now().strftime('%Y-%m-%d_%H:%M:%S'),
        'CPU_percent': cpu_total,
        'CPU_User_percent': cpu_user,
        'CPU_System_percent': cpu_system,
        'CPU_Temp_C': cpu_temp,
        'RAM_percent': memory_used_percent,
        'Swap_percent': swap_used_percent,
        'Disk_Read_B': disk_read,
        'Disk_Write_B': disk_write,
        'Disk_Read_Time_ms': disk_read_time,
        'Disk_Write_Time_ms': disk_write_time,
        'Net_Sent_B': bytes_sent,
        'Net_Recv_B': bytes_received,
        'Net_Loopback_Sent_B': loopback_sent,
        'Net_Loopback_Recv_B': loopback_recv
    }

def write_to_csv(file_name, fieldnames, data):
    with open(file_name, mode='a', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if file.tell() == 0:
            writer.writeheader()
        writer.writerow(data)

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <global_run_id>")
        sys.exit(1)

    global_run_id = sys.argv[1]

    # Create a unique filename in the logs directory
    output_dir = Path("meter_logs_hardware")
    output_dir.mkdir(parents=True, exist_ok=True)
    file_name = output_dir / f"hardware_data_{global_run_id}.csv"

    fieldnames = ['global_run_id', 'Time', 'CPU_percent', 'CPU_User_percent', 'CPU_System_percent', 'CPU_Temp_C', 'RAM_percent',
                  'Swap_percent', 'Disk_Read_B', 'Disk_Write_B', 'Disk_Read_Time_ms', 'Disk_Write_Time_ms',
                  'Net_Sent_B', 'Net_Recv_B', 'Net_Loopback_Sent_B', 'Net_Loopback_Recv_B']

    print("Starting monitoring. Press Ctrl+C to stop.")
    try:
        while True:
            metrics = get_system_metrics(global_run_id)
            write_to_csv(file_name, fieldnames, metrics)
            time.sleep(1)  # Wait 1 second before the next measurement
    except KeyboardInterrupt:
        print("\nMonitoring stopped by the user.")
    finally:
        print(f"Data has been saved to {file_name}")

if __name__ == "__main__":
    main()