import os
import requests
import time
import hmac
import hashlib
import random
from datetime import datetime
import csv
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Configuration
URL = "https://api.ecoflow.com"
QUOTA_PATH = "/iot-open/sign/device/quota/all"
ACCESS_KEY = os.getenv("ECOFLOW_ACCESS_KEY")
SECRET_KEY = os.getenv("ECOFLOW_SECRET_KEY")
SN = os.getenv("ECOFLOW_SN")
INTERVAL = 1 # seconds between each request
output_dir = Path("meter_logs_ecoflow")
output_dir.mkdir(parents=True, exist_ok=True)



# Checks if at least one argument was passed (the script name counts as an argument)
if len(sys.argv) < 2:
    print("Usage: python script.py <run_id>")
    sys.exit(1)  # Exit the script with an error code

# The first argument (sys.argv[1]) is the run_id
run_id = sys.argv[1]

CSV_FILE = output_dir / f"ecoflow_data_{run_id}.csv" # CSV file name

# Script start time
start_time = time.time()

def generate_signature(sn, access_key, nonce, timestamp, secret_key):
    str_to_sign = f"sn={sn}&accessKey={access_key}&nonce={nonce}&timestamp={timestamp}"
    return hmac.new(secret_key.encode('utf-8'), str_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

def make_request():
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))

    sign = generate_signature(SN, ACCESS_KEY, nonce, timestamp, SECRET_KEY)

    headers = {
        "accessKey": ACCESS_KEY,
        "timestamp": timestamp,
        "nonce": nonce,
        "sign": sign
    }

    try:
        response = requests.get(
            f"{URL}{QUOTA_PATH}",
            params={"sn": SN},
            headers=headers,
            json={"sn": SN},
            timeout=10
        )
        response.raise_for_status()

        json_response = response.json()
        data = json_response.get('data', {})

        watts_value = data.get('2_1.watts')
        volt_value = data.get('2_1.volt')
        current_value = data.get('2_1.current')
        temp_value = data.get('2_1.temp')

        datenow = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        duration = int(time.time() - start_time)

        if watts_value is not None:
            adjusted_watts = float(watts_value) * 0.1
            return {
                'run_id': run_id,
                'datenow': datenow,
                'duration': duration,
                'watts': f"{adjusted_watts:.1f}",
                'volt': volt_value,
                'current': current_value,
                'temp': temp_value
            }
        else:
            print(f"[{datenow}] Error: Could not get values")
            return None

    except requests.exceptions.RequestException as e:
        datenow = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        print(f"[{datenow}] Error making request: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response content: {e.response.text}")
        return None

def write_to_csv(data):
    file_exists = False
    try:
        with open(CSV_FILE, 'r') as f:
            file_exists = True
    except FileNotFoundError:
        pass

    with open(CSV_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['run_id', 'datenow', 'duration', 'watts', 'volt', 'current', 'temp'])
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)

def main():
    print(f"Starting monitoring of multiple values for run_id: {run_id}. Data will be saved to {CSV_FILE}. Press Ctrl+C to stop.")
    try:
        while True:
            data = make_request()
            if data:
                write_to_csv(data)
                # print(f"Ecoflow {CSV_FILE}: {data}")
                print(f"Ecoflow : datenow={data['datenow']}, duration={data['duration']}, watts={data['watts']} , volt={data['volt']}  , current={data['current']} , temp={data['temp']}")
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")

if __name__ == "__main__":
    main()