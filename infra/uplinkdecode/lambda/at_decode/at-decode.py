# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import json
import base64
import struct
import boto3
from datetime import datetime

# Constants
TOPIC_NAME = 'iot/assettracker'
payload_table_name = os.environ.get('UPLINK_PAYLOAD_TABLE', 'at-payloads')

# Initialize AWS clients
iot_data_client = boto3.client('iot-data')
dynamodb_client = boto3.client('dynamodb')
iot_wireless_client = boto3.client('iotwireless')


def decode_payload(payload_data):
    """
    Decode base64 payload, handling both raw bytes and hex-encoded strings.
    """
    decoded = base64.b64decode(payload_data)
    
    # Check if this looks like a hex string (10 ASCII hex chars for 5 bytes)
    if len(decoded) == 10:
        try:
            hex_str = decoded.decode('ascii')
            if all(c in '0123456789abcdefABCDEF' for c in hex_str):
                return bytes.fromhex(hex_str)
        except (UnicodeDecodeError, ValueError):
            pass
    
    return decoded


def detect_message_type(event):
    """
    Detect if message is sensor telemetry or location message.
    """
    wireless_metadata = event.get('WirelessMetadata', {})
    sidewalk_metadata = wireless_metadata.get('Sidewalk', {})
    
    if sidewalk_metadata.get('MessageType') == 'LOCATION':
        return 'LOCATION'
    
    if 'Location' in sidewalk_metadata:
        return 'LOCATION'
    
    if 'GeoJsonPayload' in event:
        return 'LOCATION'
    
    if event.get('type') == 'Point' and 'properties' in event:
        return 'LOCATION'
    
    payload_data = event.get('PayloadData', '')
    if payload_data:
        try:
            decoded = decode_payload(payload_data)
            if len(decoded) == 5:
                return 'SENSOR_TELEMETRY'
        except Exception:
            pass
    
    return 'UNKNOWN'


def calculate_battery_percent(mv):
    """Convert millivolts to battery percentage (3000mV=0%, 4200mV=100%)"""
    MIN_MV = 3000
    MAX_MV = 4200
    percent = ((mv - MIN_MV) / (MAX_MV - MIN_MV)) * 100
    return max(0, min(100, int(percent)))


def get_readable_timestamp(timestamp_ms):
    """Convert epoch milliseconds to ISO 8601 format."""
    return datetime.utcfromtimestamp(timestamp_ms / 1000).isoformat() + 'Z'


def fetch_device_position(device_id):
    """
    Fetch the current position of a wireless device using GetResourcePosition API.
    """
    try:
        response = iot_wireless_client.get_resource_position(
            ResourceIdentifier=device_id,
            ResourceType='WirelessDevice'
        )
        
        geo_json_body = response.get('GeoJsonPayload')
        if geo_json_body:
            geo_json_str = geo_json_body.read().decode('utf-8')
            return json.loads(geo_json_str)
        return None
    except iot_wireless_client.exceptions.ResourceNotFoundException:
        print(f"No position found for device {device_id}")
        return None
    except Exception as e:
        print(f"Error fetching device position: {e}")
        return None


def parse_sensor_payload(payload):
    """
    Parse 5-byte sensor telemetry payload.
    """
    if len(payload) != 5:
        raise ValueError(f"Invalid sensor payload length: {len(payload)}")
    
    temperature = struct.unpack('b', bytes([payload[0]]))[0]
    humidity = payload[1]
    battery_mv = struct.unpack('>H', payload[2:4])[0]
    status_flags = payload[4]
    battery_percent = calculate_battery_percent(battery_mv)
    
    return {
        'temperature': temperature,
        'humidity': humidity,
        'batteryMv': battery_mv,
        'batteryPercent': battery_percent,
        'statusFlags': status_flags
    }


def parse_location_from_event(event, device_id):
    """
    Extract location data from event, fetching via API if coordinates missing.
    """
    location_data = None
    
    sidewalk_metadata = event.get('WirelessMetadata', {}).get('Sidewalk', {})
    if 'Location' in sidewalk_metadata:
        location_data = sidewalk_metadata['Location']
    
    if not location_data and 'GeoJsonPayload' in event:
        geo_payload = event['GeoJsonPayload']
        if isinstance(geo_payload, str):
            location_data = json.loads(geo_payload)
        else:
            location_data = geo_payload
    
    if not location_data and event.get('type') == 'Point':
        location_data = event
    
    if not location_data:
        return None
    
    if location_data.get('type') != 'Point':
        return None
    
    coordinates = location_data.get('coordinates', [])
    properties = location_data.get('properties', {})
    
    if len(coordinates) < 2:
        print(f"Coordinates missing, fetching via GetResourcePosition API for device {device_id}")
        fetched_position = fetch_device_position(device_id)
        
        if fetched_position and fetched_position.get('type') == 'Point':
            coordinates = fetched_position.get('coordinates', [])
            fetched_props = fetched_position.get('properties', {})
            properties = {**properties, **fetched_props}
            print(f"Fetched coordinates: {coordinates}")
    
    if len(coordinates) < 2:
        return None
    
    return {
        'latitude': float(coordinates[1]),
        'longitude': float(coordinates[0]),
        'accuracy': float(properties.get('horizontalAccuracy', 100)),
        'coordinates': coordinates,
        'properties': properties
    }


def store_sensor_telemetry(device_id, timestamp, sensor_data):
    """Store sensor telemetry data in DynamoDB."""
    try:
        item = {
            'WirelessDeviceId': {'S': device_id},
            'timestamp': {'N': str(timestamp)},
            'datetime': {'S': get_readable_timestamp(timestamp)},
            'type': {'S': 'SENSOR'},
            'temperature': {'N': str(sensor_data['temperature'])},
            'humidity': {'N': str(sensor_data['humidity'])},
            'batteryMv': {'N': str(sensor_data['batteryMv'])},
            'batteryPercent': {'N': str(sensor_data['batteryPercent'])},
            'statusFlags': {'N': str(sensor_data['statusFlags'])}
        }
        
        response = dynamodb_client.put_item(
            TableName=payload_table_name,
            Item=item
        )
        print(f"DynamoDB sensor write response: {response}")
    except Exception as e:
        print(f"Error writing sensor telemetry to DynamoDB: {e}")
        raise


def store_location_telemetry(device_id, timestamp, location_data):
    """Store location telemetry data in DynamoDB."""
    try:
        item = {
            'WirelessDeviceId': {'S': device_id},
            'timestamp': {'N': str(timestamp)},
            'datetime': {'S': get_readable_timestamp(timestamp)},
            'type': {'S': 'LOCATION'},
            'latitude': {'N': str(location_data['latitude'])},
            'longitude': {'N': str(location_data['longitude'])},
            'accuracy': {'N': str(location_data.get('accuracy', 100))}
        }
        
        response = dynamodb_client.put_item(
            TableName=payload_table_name,
            Item=item
        )
        print(f"DynamoDB location write response: {response}")
    except Exception as e:
        print(f"Error writing location telemetry to DynamoDB: {e}")
        raise


def construct_tracker_payload(location_response, timestamp, batt):
    """Construct payload for IoT topic publication."""
    coor = location_response.get("coordinates")
    prop = location_response.get("properties")
    return {
        'deviceId': 'assettracker',
        'timestamp': timestamp,
        'latitude': coor[1],
        'longitude': coor[0],
        'accuracy': {'horizontal': prop.get("horizontalAccuracy")},
        'positionProperties': {'batteryLevel': batt}
    }


def publish_to_iot(payload):
    """Publish location payload to IoT topic."""
    try:
        response = iot_data_client.publish(
            topic=TOPIC_NAME,
            qos=0,
            payload=json.dumps(payload)
        )
        print(f"IoT Data Response: {response}")
    except Exception as e:
        print(f"Error publishing to IoT: {e}")
        raise


def handle_sensor_telemetry(device_id, payload, metadata, timestamp):
    """
    Handle sensor telemetry message.
    """
    sensor_data = parse_sensor_payload(payload)
    
    print(f'Sensor telemetry - Device: {device_id}, '
          f'Temp: {sensor_data["temperature"]}°C, '
          f'Humidity: {sensor_data["humidity"]}%, '
          f'Battery: {sensor_data["batteryMv"]}mV ({sensor_data["batteryPercent"]}%), '
          f'Status: {sensor_data["statusFlags"]}')
    
    # Store sensor data in DynamoDB
    store_sensor_telemetry(device_id, timestamp, sensor_data)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Sensor telemetry processed',
            'deviceId': device_id,
            'data': sensor_data
        })
    }


def handle_location_message(device_id, event, metadata, timestamp):
    """
    Handle location message.
    """
    location_data = parse_location_from_event(event, device_id)
    
    if not location_data:
        print(f"Could not obtain location for device {device_id}")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Could not obtain coordinates for device'})
        }
    
    print(f'Location message - Device: {device_id}, '
          f'Lat: {location_data["latitude"]}, '
          f'Lon: {location_data["longitude"]}, '
          f'Accuracy: {location_data["accuracy"]}m')
    
    # Store location data in DynamoDB
    store_location_telemetry(device_id, timestamp, location_data)
    
    # Publish to IoT
    location_response = {
        'type': 'Point',
        'coordinates': location_data['coordinates'],
        'properties': location_data['properties']
    }
    tracker_payload = construct_tracker_payload(location_response, timestamp, 100)
    publish_to_iot(tracker_payload)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Location message processed',
            'deviceId': device_id,
            'location': {
                'latitude': location_data['latitude'],
                'longitude': location_data['longitude'],
                'accuracy': location_data['accuracy']
            }
        })
    }


def lambda_handler(event, context):
    """
    Main Lambda handler for processing Sidewalk uplink messages.
    
    Supports two message types:
    - SENSOR_TELEMETRY: 5-byte payload with temperature, humidity, battery, status
    - LOCATION: GeoJSON with pre-resolved GPS coordinates from Sidewalk
    """
    print(f'Received event: {json.dumps(event)}')
    
    timestamp = int(datetime.utcnow().timestamp() * 1000)
    
    if 'at_uplink' in event:
        uplink = event.get('at_uplink')
        device_id = uplink.get('WirelessDeviceId')
        wireless_metadata = uplink.get('WirelessMetadata', {})
        payload_data = uplink.get('PayloadData', '')
    else:
        device_id = event.get('WirelessDeviceId')
        wireless_metadata = event.get('WirelessMetadata', {})
        payload_data = event.get('PayloadData', '')
    
    if not device_id:
        print("Missing WirelessDeviceId")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing WirelessDeviceId'})
        }
    
    sidewalk_metadata = wireless_metadata.get('Sidewalk', {})
    detection_event = event.get('at_uplink', event)
    message_type = detect_message_type(detection_event)
    
    print(f'Detected message type: {message_type} for device {device_id}')
    
    try:
        if message_type == 'LOCATION':
            return handle_location_message(device_id, detection_event, sidewalk_metadata, timestamp)
        
        elif message_type == 'SENSOR_TELEMETRY':
            decoded_payload = decode_payload(payload_data)
            return handle_sensor_telemetry(device_id, decoded_payload, sidewalk_metadata, timestamp)
        
        else:
            print(f'Unknown message type for device {device_id}')
            return {
                'statusCode': 422,
                'body': json.dumps({'error': 'Unknown message type'})
            }
    
    except Exception as e:
        print(f"Error processing message: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
