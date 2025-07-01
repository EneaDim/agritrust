# scripts/backend.py
# ====== Import =======
import os
import sqlite3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List
import threading
import json
import paho.mqtt.client as mqtt

## ==== Load Environment =====
#from dotenv import load_dotenv
#load_dotenv()

# ========== Parametri da ambiente ==========
USE_MQTT = os.getenv("USE_MQTT", "0") == "1"
DB_FILE = os.getenv("DB_FILE", "sensordata.db")
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "sensor/data")

# ========== Inizializzazione App ==========
app = FastAPI()

# ========== Modello dati ==========
class SensorData(BaseModel):
    temperature: float
    humidity: float
    luminosity: float
    gps: Dict[str, float]
    signature: str

# ========== Connessione al database ==========
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS sensor_data (
        temperature REAL,
        humidity REAL,
        luminosity REAL,
        lat REAL,
        lon REAL,
        signature TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()

# ========== Verifica della firma (mock) ==========
def verify_signature(data: dict) -> bool:
    return data.get('signature') == 'dummy_signature'

# ========== Inserimento nel DB ==========
def save_to_db(sensor_data: SensorData):
    c.execute('''
        INSERT INTO sensor_data (temperature, humidity, luminosity, lat, lon, signature)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        sensor_data.temperature,
        sensor_data.humidity,
        sensor_data.luminosity,
        sensor_data.gps['lat'],
        sensor_data.gps['lon'],
        sensor_data.signature
    ))
    conn.commit()

# ========== MQTT Listener ==========
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        sensor_data = SensorData(**payload)
        if verify_signature(payload):
            save_to_db(sensor_data)
            print(f"✅ MQTT: Dati salvati da topic '{msg.topic}'")
        else:
            print("⚠️  MQTT: Firma non valida.")
    except Exception as e:
        print(f"❌ MQTT: Errore nel parsing: {e}")

def start_mqtt_listener():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe(MQTT_TOPIC)
    client.loop_forever()

if USE_MQTT:
    thread = threading.Thread(target=start_mqtt_listener, daemon=True)
    thread.start()
    print(f"📡 MQTT attivo: ascolto su {MQTT_BROKER}:{MQTT_PORT} topic '{MQTT_TOPIC}'")

# ========== Endpoint FastAPI ==========
@app.get("/")
async def root():
    return {"message": "Backend attivo!"}

@app.post("/data")
async def receive_data(sensor_data: SensorData):
    if not verify_signature(sensor_data.dict()):
        raise HTTPException(status_code=400, detail="Invalid signature")
    save_to_db(sensor_data)
    return {"status": "success"}

@app.get("/data")
async def get_all_data():
    c.execute("SELECT temperature, humidity, luminosity, lat, lon, signature, timestamp FROM sensor_data ORDER BY timestamp DESC")
    rows = c.fetchall()
    result = [
        {
            "temperature": r[0],
            "humidity": r[1],
            "luminosity": r[2],
            "gps": {"lat": r[3], "lon": r[4]},
            "signature": r[5],
            "timestamp": r[6]
        } for r in rows
    ]
    return {"data": result}

@app.get("/status")
async def status():
    try:
        c.execute("SELECT COUNT(*) FROM sensor_data")
        count = c.fetchone()[0]
        return {"status": "ok", "records": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

