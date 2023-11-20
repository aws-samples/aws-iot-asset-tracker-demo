import os
import json
import base64
import boto3
from datetime import datetime

# Constants
TOPIC_NAME = 'iot/assettracker'

iot_wireless_client = boto3.client('iotwireless')
iot_data_client = boto3.client('iot-data')
dynamodb_client = boto3.client('dynamodb')
# payload_table_name = os.environ.get('UPLINK_PAYLOAD_TABLE')
payload_table_name = 'at-payloads'

def decode_payload(data):
    data_bytes = data.encode('ascii')
    decoded = base64.b64decode(data_bytes).decode('ascii')
    # print(decoded)
    return decoded

def get_uplink_type(decoded_bytes):
    at_uplink_t = (decoded_bytes[0] & 0xC0) >> 6
    uplink_types = ["CONFIG", "NOLOC", "WIFI", "GNSS"]
    return uplink_types[at_uplink_t] if at_uplink_t < len(uplink_types) else "unknown"

def to_signed_byte(byte):
    return byte - 256 if byte > 127 else byte

def format_mac_address(mac_bytes):
    mac = mac_bytes.hex()
    return ':'.join(mac[i:i + 2] for i in range(0, len(mac), 2))

def lambda_handler(event, context):
    print(f'Received event: {event}')
    
    uplink = event.get("at_uplink")
    if not uplink:
        return {
            'statusCode': 400,
            'body': json.dumps('Unsupported request received. Only at_uplink is supported')
        }
    
    timestamp = int(datetime.utcnow().timestamp() * 1000)
    devid = uplink.get("WirelessDeviceId")
    seq = uplink.get("WirelessMetadata").get("Seq")
    payload = decode_payload(uplink.get("PayloadData"))
    decoded_bytes = bytearray.fromhex(payload)
    at_uplink_type = get_uplink_type(decoded_bytes)
    
    match at_uplink_type:
        case "CONFIG":
            print(f'CONFIG! TBD')
        case "NOLOC":
            # Extracting the data
            batt = decoded_bytes[1]
            temp = to_signed_byte(decoded_bytes[2])
            hum = int(decoded_bytes[3])
            motion = bool((decoded_bytes[4] & 0x80))
            max_accel = float(decoded_bytes[4] & 0x7F) / 10

            print(f'WirelessDeviceId: {devid}, '
                f'Uplink Type: {at_uplink_type}, '
                f'Timestamp: {timestamp}, '
                f'Seq: {seq}, '
                f'Battery: {batt}%, '
                f'Temperature: {temp}C, '
                f'RH: {hum}%, '
                f'Motion: {motion}, '
                f'Max Accel: {max_accel}g')

			# write_to_payloads_table
            try:
                response = dynamodb_client.put_item(
                    TableName=payload_table_name,
                    Item={
                        'WirelessDeviceId': {'S': devid},
                        'timestamp': {'N': int(timestamp)},
                        'seq': {'N': int(seq)},
                        'type': {'S': at_uplink_type},
                        'battery': {'N': int(batt)},
                        'temperature': {'N': int(temp)},
                        'humidity': {'N': int(hum)},
                        'motion': {'S': str(motion)},
                        'max accel': {'N': max_accel}
                    }
                )
                print(f"DynamoDB write response: {response}")
            except Exception as e:
                print(f"Error writing to DynamoDB payloads table: {e}")

        case "WIFI":
            # Check if this is a fragment
            num_msg = (decoded_bytes[0] & 0x38)>>3
            if num_msg == 1:
                batt = decoded_bytes[1]
                temp = to_signed_byte(decoded_bytes[2])
                hum = int(decoded_bytes[3])
                motion = bool((decoded_bytes[4] & 0x80))
                max_accel = float(decoded_bytes[4] & 0x7F) / 10
                rssi1 = to_signed_byte(decoded_bytes[5])
                mac1 = format_mac_address(decoded_bytes[6:12])
                rssi2 = to_signed_byte(decoded_bytes[12])
                mac2 = format_mac_address(decoded_bytes[13:19])

                # Print the extracted data
                print(f'WirelessDeviceId: {uplink.get("WirelessDeviceId")}, '
                    f'Seq: {uplink.get("WirelessMetadata").get("Seq")}, '
                    f'Uplink Type: {at_uplink_type}, '
                    f'Battery: {batt}%, '
                    f'Temperature: {temp}C, '
                    f'RH: {hum}%, '
                    f'Motion: {motion}, '
                    f'Max Accel: {max_accel}g, '
                    f'RSSI_1: {rssi1}, '
                    f'MAC_1: {mac1}, '
                    f'RSSI_2: {rssi2}, '
                    f'MAC_2: {mac2}')
        
                # Get location
                location_response = get_location_from_iot_wireless(mac1, rssi1, mac2, rssi2)
                print(location_response)

                tracker_location = construct_tracker_payload(location_response, timestamp, batt)

                wifi_data = [{'MacAddress': mac1, 'Rss': rssi1}, {'MacAddress': mac2, 'Rss': rssi2}]
                # write_to_payloads_table
                try:
                    response = dynamodb_client.put_item(
                        TableName=payload_table_name,
                        Item={
                            'WirelessDeviceId': {'S': devid},
                            'timestamp': {'N': str(timestamp)},
                            'seq': {'N': str(seq)},
                            'type': {'S': at_uplink_type},
                            'frag cnt': {'N': str(num_msg)},
                            'battery': {'N': str(batt)},
                            'temperature': {'N': str(temp)},
                            'humidity': {'N': str(hum)},
                            'motion': {'S': str(motion)},
                            'max accel': {'N': str(max_accel)},
                            'wifidata': {'S': json.dumps(wifi_data)},
                            'location': {'S': str(tracker_location)}
                        }
                    )
                    print(f"DynamoDB write response: {response}")
                except Exception as e:
                    print(f"Error writing to DynamoDB payloads table: {e}")

                # Construct and publish tracker location payload

                publish_to_iot(tracker_location)

            else:
                #it is a fragment.  just write it to the payloads table and let the defrag function determin the location
                frag_num = (decoded_bytes[0] & 0x7)
                if frag_num == 0:
                    batt = decoded_bytes[1]
                    temp = to_signed_byte(decoded_bytes[2])
                    hum = int(decoded_bytes[3])
                    motion = bool((decoded_bytes[4] & 0x80))
                    max_accel = float(decoded_bytes[4] & 0x7F) / 10
                    rssi1 = to_signed_byte(decoded_bytes[5])
                    mac1 = format_mac_address(decoded_bytes[6:12])
                    rssi2 = to_signed_byte(decoded_bytes[12])
                    mac2 = format_mac_address(decoded_bytes[13:19])

                    at_uplink_type = "WIFI_F"

                    # Print the extracted data
                    print(f'WirelessDeviceId: {uplink.get("WirelessDeviceId")}, '
                        f'Seq: {uplink.get("WirelessMetadata").get("Seq")}, '
                        f'Uplink Type: {at_uplink_type}, '
                        f'frag count: {num_msg}, '
                        f'Battery: {batt}%, '
                        f'Temperature: {temp}C, '
                        f'RH: {hum}%, '
                        f'Motion: {motion}, '
                        f'Max Accel: {max_accel}g, '
                        f'RSSI_1: {rssi1}, '
                        f'MAC_1: {mac1}, '
                        f'RSSI_2: {rssi2}, '
                        f'MAC_2: {mac2}')
                    
                    wifi_data = [{'MacAddress': mac1, 'Rss': rssi1}, {'MacAddress': mac2, 'Rss': rssi2}]
                    # write_to_payloads_table
                    try:
                        response = dynamodb_client.put_item(
                            TableName=payload_table_name,
                            Item={
                                'WirelessDeviceId': {'S': devid},
                                'timestamp': {'N': str(timestamp)},
                                'seq': {'N': str(seq)},
                                'type': {'S': at_uplink_type},
                                'frag cnt': {'N': str(num_msg)},
                                'battery': {'N': str(batt)},
                                'temperature': {'N': str(temp)},
                                'humidity': {'N': str(hum)},
                                'motion': {'S': str(motion)},
                                'max accel': {'N': str(max_accel)},
                                'wifidata': {'S': json.dumps(wifi_data)}
                            }
                        )
                        print(f"DynamoDB write response: {response}")
                    except Exception as e:
                        print(f"Error writing to DynamoDB payloads table: {e}")

                else:
                    rssi1 = to_signed_byte(decoded_bytes[1])
                    mac1 = format_mac_address(decoded_bytes[2:8])
                    
                    if len(payload) == 30:
                        rssi2 = to_signed_byte(decoded_bytes[8])
                        mac2 = format_mac_address(decoded_bytes[9:15])

                        # Print the extracted data for 2 macs
                        print(f'WirelessDeviceId: {uplink.get("WirelessDeviceId")}, '
                            f'Seq: {uplink.get("WirelessMetadata").get("Seq")}, '
                            f'Uplink Type: {at_uplink_type}, '
                            f'frag count: {num_msg}, '
                            f'RSSI_1: {rssi1}, '
                            f'MAC_1: {mac1}, '
                            f'RSSI_2: {rssi2}, '
                            f'MAC_2: {mac2}')
                        wifi_data = [{'MacAddress': mac1, 'Rss': rssi1}, {'MacAddress': mac2, 'Rss': rssi2}]
                    else:
                        # Print the extracted data for one mac
                        print(f'WirelessDeviceId: {uplink.get("WirelessDeviceId")}, '
                            f'Seq: {uplink.get("WirelessMetadata").get("Seq")}, '
                            f'Uplink Type: {at_uplink_type}, '
                            f'frag count: {num_msg}, '
                            f'RSSI_1: {rssi1}, '
                            f'MAC_1: {mac1}')
                        wifi_data = [{'MacAddress': mac1, 'Rss': rssi1}]
                            
                    at_uplink_type = "WIFI_END"
                    
                    
                    # write_to_payloads_table
                    try:
                        response = dynamodb_client.put_item(
                            TableName=payload_table_name,
                            Item={
                                'WirelessDeviceId': {'S': devid},
                                'timestamp': {'N': str(timestamp)},
                                'seq': {'N': str(seq)},
                                'type': {'S': at_uplink_type},
                                'frag cnt': {'N': str(num_msg)},
                                'wifidata': {'S': json.dumps(wifi_data)}
                            }
                        )
                        print(f"DynamoDB write response: {response}")
                    except Exception as e:
                        print(f"Error writing to DynamoDB payloads table: {e}")

        case "GNSS":
            print(f'GNSS!')
            num_msg = (decoded_bytes[0] & 0x38)>>3
            frag_num = (decoded_bytes[0] & 0x7)
            if frag_num == 0:
                batt = decoded_bytes[1]
                temp = to_signed_byte(decoded_bytes[2])
                hum = int(decoded_bytes[3])
                motion = bool((decoded_bytes[4] & 0x80))
                max_accel = float(decoded_bytes[4] & 0x7F) / 10
                nav_size = decoded_bytes[5]
                cap_time = int.from_bytes(decoded_bytes[6:12], "big")

                at_uplink_type = "GNSS"

                # Print the extracted data
                print(f'WirelessDeviceId: {uplink.get("WirelessDeviceId")}, '
                    f'Seq: {uplink.get("WirelessMetadata").get("Seq")}, '
                    f'Uplink Type: {at_uplink_type}, '
                    f'frag count: {num_msg}, '
                    f'Battery: {batt}%, '
                    f'Temperature: {temp}C, '
                    f'RH: {hum}%, '
                    f'Motion: {motion}, '
                    f'Max Accel: {max_accel}g, '
                    f'Nav Msg Size: {nav_size}, '
                    f'Capture Time: {cap_time}')
   
                # write_to_payloads_table
                try:
                    response = dynamodb_client.put_item(
                        TableName=payload_table_name,
                        Item={
                            'WirelessDeviceId': {'S': devid},
                            'timestamp': {'N': str(timestamp)},
                            'seq': {'N': str(seq)},
                            'type': {'S': at_uplink_type},
                            'frag cnt': {'N': str(num_msg)},
                            'battery': {'N': str(batt)},
                            'temperature': {'N': str(temp)},
                            'humidity': {'N': str(hum)},
                            'motion': {'S': str(motion)},
                            'max accel': {'N': str(max_accel)},
                            'nav msg size': {'N': str(nav_size)},
                            'capture time': {'N': str(cap_time)}
                        }
                    )
                    print(f"DynamoDB write response: {response}")
                except Exception as e:
                    print(f"Error writing to DynamoDB payloads table: {e}")

            else:
                batt = decoded_bytes[1]
                temp = to_signed_byte(decoded_bytes[2])
                hum = int(decoded_bytes[3])
                motion = bool((decoded_bytes[4] & 0x80))
                max_accel = float(decoded_bytes[4] & 0x7F) / 10

                if frag_num == 0x7:
                    at_uplink_type = "GNSS_END"
                else:
                    at_uplink_type = "GNSS_F"

                nav_frag = payload[2:]
                # Print the extracted data
                print(f'WirelessDeviceId: {uplink.get("WirelessDeviceId")}, '
                    f'Seq: {uplink.get("WirelessMetadata").get("Seq")}, '
                    f'Uplink Type: {at_uplink_type}, '
                    f'frag count: {num_msg}, '
                    f'NAV frag: {nav_frag}')
   
                # write_to_payloads_table
                try:
                    response = dynamodb_client.put_item(
                        TableName=payload_table_name,
                        Item={
                            'WirelessDeviceId': {'S': devid},
                            'timestamp': {'N': str(timestamp)},
                            'seq': {'N': str(seq)},
                            'type': {'S': at_uplink_type},
                            'frag cnt': {'N': str(num_msg)},
                            'nav frag': {'S': nav_frag}
                        }
                     )
                    print(f"DynamoDB write response: {response}")
                except Exception as e:
                    print(f"Error writing to DynamoDB payloads table: {e}")

        case _:
            print(f'Unknown uplink message type!')
            return {'statusCode': 422 }

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
    response = iot_data_client.publish(
        topic=TOPIC_NAME,
        qos=0,
        payload=json.dumps(payload)
    )
    print(f"IoT Data Response: {response}")
