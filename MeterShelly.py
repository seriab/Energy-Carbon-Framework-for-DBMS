import os
import requests
import time
import csv
import sys
from datetime import datetime
from pathlib import Path

# --- Configuration ---
# Default IP for the Shelly Plug S. Replace with your device's IP.
SHELLY_IP = "192.168.1.136"
# Interval in seconds between each data request.
REQUEST_INTERVAL = 1
# Directory to store the output file.
OUTPUT_DIR = Path("meter_logs_shelly")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
# Name of the CSV file where data will be saved.
CSV_FILE = OUTPUT_DIR / "shelly_data.csv"

# --- Main Script ---

def make_request(shelly_ip, run_id, start_time):
    """
    Makes a request to the Shelly Plug S Gen3 to get power metrics.
    """
    url = f"http://{shelly_ip}/rpc"
    payload = {"id": 1, "src": "meter", "method": "Switch.GetStatus", "params": {"id": 0}}

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()  # Raise an exception for bad status codes

        json_response = response.json()
        result = json_response.get('result', {})

        # Extract metrics from the response
        watts = result.get('apower')
        voltage = result.get('voltage')
        current = result.get('current')
        temp_c = result.get('temperature', {}).get('tC')

        datenow = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        duration = int(time.time() - start_time)

        if watts is not None:
            return {
                'run_id': run_id,
                'datenow': datenow,
                'duration': duration,
                'watts': f"{watts:.2f}",
                'voltage': f"{voltage:.1f}" if voltage is not None else None,
                'current': f"{current:.3f}" if current is not None else None,
                'temp_c': temp_c,
            }
        else:
            print(f"[{datenow}] Error: 'apower' (watts) not found in Shelly response.")
            return None

    except requests.exceptions.RequestException as e:
        datenow = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        print(f"[{datenow}] Error making request to Shelly plug: {e}")
        return None

def write_to_csv(data):
    """
    Appends a dictionary of data to the CSV file.
    """
    file_exists = CSV_FILE.exists()

    fieldnames = ['run_id', 'datenow', 'duration', 'watts', 'voltage', 'current', 'temp_c']

    with open(CSV_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)

def main():
    """
    Main loop to poll the Shelly device and save data.
    """
    if len(sys.argv) < 2:
        print("Usage: python MeterShelly.py <run_id> [shelly_ip]")
        sys.exit(1)

    run_id = sys.argv[1]
    shelly_ip = sys.argv[2] if len(sys.argv) > 2 else SHELLY_IP

    # Customize CSV file name with run_id
    global CSV_FILE
    CSV_FILE = OUTPUT_DIR / f"shelly_data_{run_id}.csv"

    if CSV_FILE.exists():
        os.remove(CSV_FILE)
        print(f"Old file {CSV_FILE} deleted.")

    start_time = time.time()

    print(f"Starting monitoring for run_id: {run_id}. Using Shelly at {shelly_ip}.")
    print(f"Data will be saved to {CSV_FILE}. Press Ctrl+C to stop.")

    try:
        while True:
            data = make_request(shelly_ip, run_id, start_time)
            if data:
                write_to_csv(data)
                # print(f"Data saved: {data['watts']} W, {data['temp_c']} C")
                # print(f"Shelly {CSV_FILE}: {data}")
                print(
                    f"Shelly  : datenow={data['datenow']}, duration={data['duration']}, watts={data['watts']}, volt={data['voltage']}, current={data['current']}, temp={data['temp_c']}")
            time.sleep(REQUEST_INTERVAL)

    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
    finally:
        print(f"Data collection finished. Final data saved in {CSV_FILE}")

if __name__ == "__main__":
    main()
