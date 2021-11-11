import json
import sys


def query_data():
    return [{ "data": 123 }]


def format_data(result):
    return result


def lambda_handler(event, context, mode = None):
    mode = mode if mode is not None else "default"

    result = query_data()
    response = format_data(result)


    return {
            'isBase64Encoded': True,
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': response
        }


if __name__ == "__main__":
    event = {}
    print(lambda_handler(event, '', mode="debug"))
