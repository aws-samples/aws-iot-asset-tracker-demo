import os
import json
import base64
import boto3
from datetime import datetime

# Constants
TOPIC_NAME = 'iot/assettracker'

iot_wireless_client = boto3.client('iotwireless')
iot_data_client = boto3.client('iot-data')
payload_table_name = os.environ.get('UPLINK_PAYLOAD_TABLE')

def decode_payload(data):
    data_bytes = data.encode('ascii')
    decoded = base64.b64decode(data_bytes).decode('ascii')
    return bytearray.fromhex(decoded)

def get_uplink_type(decoded_bytes):
    at_uplink_t = (decoded_bytes[0] & 0xF0) >> 4
    uplink_types = ["CONFIG", "NOLOC", "WIFI", "GNSS"]
    return uplink_types[at_uplink_t] if at_uplink_t < len(uplink_types) else "unknown"

def to_signed_byte(byte):
    return byte - 256 if byte > 127 else byte

def format_mac_address(mac_bytes):
    mac = mac_bytes.hex()
    return ':'.join(mac[i:i + 2] for i in range(0, len(mac), 2))

def lambda_handler(event, context):
    print(f'Received event: {event}')
    # timestamp = int(datetime.utcnow().timestamp() * 1000)
    
    # uplink = event.get("at_uplink")
    # if not uplink:
    #     return {
    #         'statusCode': 400,
    #         'body': json.dumps('Unsupported request received. Only at_uplink is supported')
    #     }
    
    # decoded_bytes = decode_payload(uplink.get("PayloadData"))
    # at_uplink_type = get_uplink_type(decoded_bytes)
    
    # # Extracting other data from decoded bytes
    # at_uplink_frag_cnt = (decoded_bytes[0] & 0x0F)
    # batt = decoded_bytes[1]
    # temp = to_signed_byte(decoded_bytes[2])
    # hum = int(decoded_bytes[3])
    # motion = bool((decoded_bytes[4] & 0x80))
    # max_accel = float(decoded_bytes[4] & 0x7F) / 10
    # rssi1 = to_signed_byte(decoded_bytes[5])
    # mac1 = format_mac_address(decoded_bytes[6:12])
    # rssi2 = to_signed_byte(decoded_bytes[12])
    # mac2 = format_mac_address(decoded_bytes[13:19])
    
    # # Print the extracted data
    # print(f'WirelessDeviceId: {uplink.get("WirelessDeviceId")}, '
    #       f'Seq: {uplink.get("WirelessMetadata").get("Sidewalk").get("Seq")}, '
    #       f'Uplink Type: {at_uplink_type}, '
    #       f'frag count: {at_uplink_frag_cnt}, '
    #       f'Battery: {batt}%, '
    #       f'Temperature: {temp}C, '
    #       f'RH: {hum}%, '
    #       f'Motion: {motion}, '
    #       f'Max Accel: {max_accel}g, '
    #       f'RSSI_1: {rssi1}, '
    #       f'MAC_1: {mac1}, '
    #       f'RSSI_2: {rssi2}, '
    #       f'MAC_2: {mac2}')

    # # Get location
    # location_response = get_location_from_iot_wireless(mac1, rssi1, mac2, rssi2)
    
    # # Construct and publish tracker location payload
    # tracker_location = construct_tracker_payload(location_response, timestamp, batt)
    # publish_to_iot(tracker_location)

    return {
        'statusCode': 200,
    }

def get_location_from_iot_wireless(mac1, rssi1, mac2, rssi2):
    response = iot_wireless_client.get_position_estimate(
        WiFiAccessPoints=[{'MacAddress': mac1, 'Rss': rssi1}, {'MacAddress': mac2, 'Rss': rssi2}],
        Timestamp=datetime.utcnow().timestamp()
    )
    return json.loads(response['GeoJsonPayload'].read())

def construct_tracker_payload(location_response, timestamp, batt):
    loc = location_response.get("location")
    coor = loc.get("coordinates")
    prop = loc.get("properties")
    
    return {
        'deviceId': 'assettracker',
        'timestamp': timestamp,
        'latitude': coor[0],
        'longitude': coor[1],
        'accuracy': {'horizontal': prop.get("horizontalAccuracy")},
        'positionProperties': {'batteryLevel': batt}
    }

def publish_to_iot(payload):
    response = iot_data_client.publish(
        topic=TOPIC_NAME,
        qos=0,
        payload=json.dumps(payload)
    )
    print(f"IoT Data Response: {response}")

