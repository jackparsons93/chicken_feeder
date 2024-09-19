import eventlet
eventlet.monkey_patch()

import json
import RPi.GPIO as GPIO
from flask import Flask, render_template
from datetime import datetime, timedelta
from flask_socketio import SocketIO, emit
import websocket
import pygame  # For playing the sound effects

# Replace with your actual values
CLIENT_ID = 'YOUR_CLIENT_ID'
CHANNEL_ID = 'YOUR_CHANNEL_ID'  # The ID of the channel you want to listen to
OAUTH_TOKEN = 'YOUR_OAUTH_TOKEN'

# Setup GPIO for Motor 2 (Chicken Feeder/Light)
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Motor 2 (Light) pin assignments
AN2 = 13  # PWM pin for Motor 2 (Light)
DIG2 = 24  # Direction pin for Motor 2 (Light)

# Setup Motor 2 pins
GPIO.setup(AN2, GPIO.OUT)
GPIO.setup(DIG2, GPIO.OUT)

# Initialize PWM for Motor 2 (Light)
p2 = GPIO.PWM(AN2, 100)  # PWM for Motor 2 (Light) at 100 Hz

# Start Motor 2 (Light) with 0% duty cycle (off)
p2.start(0)
GPIO.output(DIG2, GPIO.HIGH)  # Set direction for Motor 2 (Light)

# Cooldown state
last_motor_spin_time = None
COOLDOWN_DURATION = 60  # seconds
cooldown_active = False
cooldown_end_time = None

# Initialize pygame mixer for playing sounds
pygame.mixer.init()

def play_rooster_sound():
    pygame.mixer.music.load("rooster.mp3")
    pygame.mixer.music.play()

def play_doorbell_sound():
    pygame.mixer.music.load("doorbell.mp3")
    pygame.mixer.music.play()

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet')

@app.route("/")
def index():
    # Pass the remaining cooldown time to the template
    remaining_time = 0
    if cooldown_active and cooldown_end_time:
        remaining_time = int((cooldown_end_time - datetime.utcnow()).total_seconds())
        remaining_time = max(0, remaining_time)  # Prevent negative countdown

    return render_template("index.html", remaining_time=remaining_time)

# Function to handle bits event for Chicken Feeder (Motor 2/Light)
def handle_bits_event(data):
    global last_motor_spin_time, cooldown_active, cooldown_end_time

    user_name = data['data']['user_name']
    bits_used = int(data['data']['bits_used'])
    donation_time = datetime.fromisoformat(data['data']['time'].replace('Z', '+00:00'))

    print(f"Received {bits_used} bits from {user_name} at {donation_time}!")

    if bits_used == 1:
        # Check if enough time has passed since the last motor spin
        current_time = datetime.utcnow()
        if last_motor_spin_time is None or (current_time - last_motor_spin_time).total_seconds() >= COOLDOWN_DURATION:
            # Update the last motor spin time and calculate cooldown end time
            last_motor_spin_time = current_time
            cooldown_active = True
            cooldown_end_time = current_time + timedelta(seconds=COOLDOWN_DURATION)

            # Emit the new remaining time to clients
            remaining_time = COOLDOWN_DURATION
            socketio.emit('update_timer', {'remaining_time': remaining_time})

            # Play doorbell sound
            print("Playing doorbell sound for 1-bit donation!")
            play_doorbell_sound()

            # Turn on the motor (light) for 0.5 seconds
            print("Turning on Motor 2 (Light) for 0.5 seconds")
            p2.ChangeDutyCycle(100)  # Turn on Motor 2 (Light) at full speed
            eventlet.sleep(0.5)  # Keep the light on for 0.5 seconds
            p2.ChangeDutyCycle(0)  # Turn off Motor 2 (Light)
            print("Motor 2 (Light) turned off after 0.5 seconds")
        else:
            time_remaining = COOLDOWN_DURATION - (current_time - last_motor_spin_time).total_seconds()
            print(f"Motor 2 (Light) is on cooldown. Time remaining: {time_remaining:.1f} seconds")

    elif bits_used == 2:
        # Handle 2-bit donation by playing rooster sound
        print("Playing rooster sound for 2-bit donation!")
        play_rooster_sound()

    else:
        print(f"Ignoring bits event with {bits_used} bits.")

# Listen to Twitch PubSub
def listen_to_twitch():
    uri = "wss://pubsub-edge.twitch.tv"

    while True:
        try:
            ws = websocket.create_connection(uri)
            print("Connected to Twitch PubSub")

            # Send LISTEN command
            topics = [f"channel-bits-events-v2.{CHANNEL_ID}"]
            listen_command = {
                "type": "LISTEN",
                "nonce": "unique_nonce_value",
                "data": {
                    "topics": topics,
                    "auth_token": OAUTH_TOKEN.replace('oauth:', '')
                }
            }
            ws.send(json.dumps(listen_command))
            print(f"Listening on topic: {topics}")

            # Start a keep-alive ping
            def send_ping():
                while True:
                    ws.send(json.dumps({"type": "PING"}))
                    eventlet.sleep(300)  # Send every 5 minutes

            eventlet.spawn_n(send_ping)

            # Handle incoming messages
            while True:
                response = ws.recv()
                message = json.loads(response)
                print("Received message:", message)

                if message['type'] == "MESSAGE":
                    data = json.loads(message['data']['message'])
                    topic = message['data']['topic']

                    if "bits" in topic:
                        handle_bits_event(data)

        except Exception as e:
            print(f"Connection lost or error: {e}. Retrying in 10 seconds...")
            eventlet.sleep(10)  # Wait 10 seconds before retrying

# Start Twitch PubSub listening as a background task
def start_twitch_listener():
    eventlet.spawn_n(listen_to_twitch)

# Handle client connections
@socketio.on('connect')
def handle_connect():
    print("Client connected")

if __name__ == "__main__":
    # Start the Twitch PubSub listener
    start_twitch_listener()

    # Start the Flask-SocketIO server
    socketio.run(app, host="0.0.0.0", port=5001)
