import os
import json
import base64
import boto3
import time
from decimal import Decimal
from typing import List, Dict, Tuple, Any, Optional
from boto3.dynamodb.conditions import Key, Attr
from datetime import datetime

# Constants
TOPIC_NAME = 'iot/assettracker'

iot_wireless_client = boto3.client('iotwireless')
iot_data_client = boto3.client('iot-data')
dynamodb = boto3.resource('dynamodb')
# payload_table_name = os.environ.get('UPLINK_PAYLOAD_TABLE')
payload_table = dynamodb.Table('at-payloads')

def lambda_handler(event, context):
    print(f'Received event: {event}')
    timestamp = int(datetime.utcnow().timestamp() * 1000)
    current_time = time.time()
    # frag window of past 5min in ms
    frag_window = (int(current_time) - 300) * 1000 

    # Get the wireless device id
    
    for record in event['Records']:
        devid = record['dynamodb']['Keys']['WirelessDeviceId']['S']
        type = record['dynamodb']['NewImage']['type']['S']
        last_frag = record['dynamodb']['NewImage']['seq']['N']
        frag_cnt = record['dynamodb']['NewImage']['frag cnt']['N']
        
    
    first_frag = str(int(last_frag) - int(frag_cnt) + 1)
    
    print(f'WirelessDeviceId: {devid}, '
        f'Type: {type}, '
        f'Frag window: {frag_window}, '
        f'First Frag: {first_frag}, '
        f'Last Frag: {last_frag}, '
        f'Frag count: {frag_cnt}')
    

    response = payload_table.query(
        KeyConditionExpression=Key('WirelessDeviceId').eq(devid) & Key('timestamp').gt(int(frag_window)),
        FilterExpression=Attr('seq').gte(int(first_frag)) & Attr('seq').lte(int(last_frag))
    )

    items = response['Items']
    
    print(items)

    match type:
        case 'WIFI_END':
            frag_count_correct, combined_wifi_data = process_wifi_entries(items)
            if frag_count_correct:
                print("Combined WiFi Data:", combined_wifi_data)
                #get the timestamp of the first message
                first_timestamp = None
                for entry in items:
                    if entry.get('type') == 'WIFI_F':
                        first_timestamp = entry['timestamp']
                
                print("First Frag Timestamp:", first_timestamp)
                
                iot_response = iot_wireless_client.get_position_estimate(
                    WiFiAccessPoints=combined_wifi_data,
                    Timestamp=datetime.utcnow().timestamp()
                )

                # TODO - if a position is resolved, write it back to the first frag entry in the payloads table
                geo_location = json.loads(iot_response['GeoJsonPayload'].read())
                print(geo_location)
                tracker_location = construct_tracker_payload_wifi(geo_location, first_timestamp)
                # try:
                #     response = dynamodb.updateitem(
                #         Key = {'WirelessDeviceId': {'S': devid}, 'timestamp': {'N': str(first_timestamp)}},
                #         UpdateExpression="set location=:p",
                #         ExpressionAttributeValues={":p": geo_location},
                #         ReturnValues="UPDATED_NEW",
                #     )
                #     print(f"DynamoDB write response: {response}")
                # except Exception as e:
                #     print(f"Error writing to DynamoDB payloads table: {e}")
                
                #then send the location to the tracker topic
                publish_to_iot(tracker_location)

            else:
                print("WiFi fragments missing!")
                return {'statusCode': 404}
                
        case 'GNSS_END':
            frag_count_correct, concatenated_nav_msg, capture_time = process_gnss_data(items)
            if frag_count_correct:
                print("Recovered NAV msg:", concatenated_nav_msg)
                print("Capture Time:", capture_time)
                #get the timestamp of the first message
                first_timestamp = None
                for entry in items:
                    if entry.get('type') == 'GNSS':
                        first_timestamp = entry['timestamp']
                print("First Frag Timestamp:", first_timestamp)

                iot_response = iot_wireless_client.get_position_estimate(
                    Gnss={
                        'Payload': str(concatenated_nav_msg),
                        'CaptureTime': float(capture_time)
                        }
                )
                
                # TODO - if a position is resolved, write it back to the first frag entry in the payloads table
                geo_location = json.loads(iot_response['GeoJsonPayload'].read())
                print(geo_location)
                tracker_location = construct_tracker_payload_gnss(geo_location, first_timestamp)
                # try:
                #     response = dynamodb.updateitem(
                #         Key = {'WirelessDeviceId': {'S': devid}, 'timestamp': {'N': str(first_timestamp)}},
                #         UpdateExpression="set location=:p",
                #         ExpressionAttributeValues={":p": geo_location},
                #         ReturnValues="UPDATED_NEW",
                #     )
                #     print(f"DynamoDB write response: {response}")
                # except Exception as e:
                #     print(f"Error writing to DynamoDB payloads table: {e}")
                
                #then send the location to the tracker topic
                publish_to_iot(tracker_location)

            else:
                print("GNSS fragments missing!")
                return {'statusCode': 404}


    return {'statusCode': 200 }

# AICDL is flipping LON-LAT for GNSS, thus requring diff functions
def construct_tracker_payload_gnss(location_response, timestamp):
    # loc = location_response.get("location")
    coor = location_response.get("coordinates")
    prop = location_response.get("properties")
    
    return {
        'deviceId': 'assettracker',
        'timestamp': int(timestamp),
        'latitude': coor[0],
        'longitude': coor[1],
        'accuracy': {'horizontal': prop.get("horizontalAccuracy")},
        'positionProperties': {'batteryLevel': 95}
    }

def construct_tracker_payload_wifi(location_response, timestamp):
    # loc = location_response.get("location")
    coor = location_response.get("coordinates")
    prop = location_response.get("properties")
    
    return {
        'deviceId': 'assettracker',
        'timestamp': int(timestamp),
        'latitude': coor[1],
        'longitude': coor[0],
        'accuracy': {'horizontal': prop.get("horizontalAccuracy")},
        'positionProperties': {'batteryLevel': 95}
    }

def publish_to_iot(payload):
    response = iot_data_client.publish(
        topic=TOPIC_NAME,
        qos=0,
        payload=json.dumps(payload)
    )
    print(f"IoT Data Response: {response}")
    
def process_wifi_entries(entries: List[Dict]) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Processes a list of Wi-Fi data entries.

    Args:
    entries (List[Dict]): List of dictionaries containing Wi-Fi data.

    Returns:
    Tuple[bool, List[Dict[str, Any]]]: A tuple containing:
        - A boolean indicating if the total number of entries matches the 'frag cnt'.
        - A combined list of all 'wifidata' objects.
    """
    # Check if total number of entries matches the 'frag cnt' value
    frag_count_correct = len(entries) == entries[0]['frag cnt'] if entries else False

    # Combine 'wifidata' into a single list
    combined_wifi_data = []
    for entry in entries:
        if 'wifidata' in entry:
            wifi_data = json.loads(entry['wifidata'])
            combined_wifi_data.extend(wifi_data)

    return frag_count_correct, combined_wifi_data
    

def process_gnss_data(data: List[Dict]) -> Tuple[bool, str, Optional[Decimal]]:
    """
    Processes a list of GNSS data dictionaries.

    Args:
    data (List[Dict]): List of dictionaries containing GNSS data.

    Returns:
    Tuple[bool, str, Optional[Decimal]]: A tuple containing:
        - A boolean indicating if the fragment count is correct.
        - A string with the concatenated 'nav msg' values.
        - The 'capture time' from the first 'seq' message, or None if not present.
    """

    # Check if the total number of entries matches the 'frag cnt' value
    frag_count_correct = len(data) == data[0]['frag cnt'] if data else False

    # Sort the data by 'seq' and concatenate 'nav frag' values
    sorted_data = sorted([d for d in data if 'nav frag' in d], key=lambda x: x['seq'])
    concatenated_nav_msg = ''.join(d['nav frag'] for d in sorted_data)

    # Extract the 'capture time' from the first 'seq' message
    capture_time = min(data, key=lambda x: x['seq']).get('capture time', None) if data else None

    return frag_count_correct, concatenated_nav_msg, capture_time

