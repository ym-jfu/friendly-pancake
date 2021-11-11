# assumptions:
# 1. executor exists called dcs-api-lambda-{env}-executor
# 2. vpc/security group exists

import boto3
import argparse
import io
import zipfile
import time
import json


def get_latest_lambda_layer_version(client, environment_abbreviation):
    paginator = client.get_paginator('list_layer_versions')
    layer_name = "dcs-api-{}".format(environment_abbreviation)

    response = paginator.paginate(
        CompatibleRuntime='python3.8',
        LayerName=layer_name
    )

    layer_versions = []
    for p in response:
        layer_versions.extend(p['LayerVersions'])

    return max(layer_versions, key=lambda x: x['Version'])


def generate_zip(file_name):
    mem_zip = io.BytesIO()

    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        with open(file_name, 'rb') as fh:
            zinfo = zipfile.ZipInfo("lambda_function.py")
            zinfo.external_attr = 0o644 << 16
            zf.writestr(zinfo, fh.read())

    return mem_zip.getvalue()

def upsert_lambda(client, file_name, environment, timeout, memory, vpc_config):
    func = None
    version = "v1"
    environment_abbreviation = "prod" if environment == "production" else "stg"
    path_part = "-".join(file_name \
                         .replace("/lambda_function.py", "") \
                         .replace("lambdas/", "") \
                         .split("/"))
    name = "dcs-{}-{}-{}".format(environment_abbreviation, version, path_part)

    try:
        func = client.get_function(
            FunctionName=name
        )
    except client.exceptions.ResourceNotFoundException as e:
        func = None
    if func:
        print("Running update on {}".format(name))
        update_lambda(client, func, name, environment_abbreviation, file_name)
    else:
        print("Running create on {}".format(name))
        create_lambda(client, name, environment, environment_abbreviation, timeout, memory, file_name, vpc_config)

def update_lambda(client, lambda_func, name, environment_abbreviation, file_name):

    layers = [get_latest_lambda_layer_version(client, environment_abbreviation)['LayerVersionArn']]

    # assumes only 1 layer used
    if 'Layers' in lambda_func['Configuration']:
        current_layers = [x['Arn'] for x in lambda_func['Configuration']['Layers']]
    else:
        current_layers = ["-1"]

    if current_layers != layers:
        client.update_function_configuration(
            FunctionName=name,
            Layers=layers
        )
        print("Updated lambda function layer for: {}\nBefore: {}\n After:{}".format(
            name,
            current_layers,
            layers
        ))

    time.sleep(45)

    # update code 2nd, otherwise updating code puts Lambda in a state where the Lambda layer cannot be changed
    zipfile_obj = generate_zip(file_name)
    client.update_function_code(
        FunctionName=name,
        ZipFile=zipfile_obj,
        Publish=True,
        DryRun=False
    )


def create_lambda(client,
                  name,
                  environment,
                  environment_abbreviation,
                  timeout,
                  memory,
                  file_name,
                  vpc_config):

    sts_client = boto3.client("sts")
    account_id = sts_client.get_caller_identity()["Account"]

    role = "arn:aws:iam::{}:role/dcs-api-lambda-{}-executor".format(account_id, environment)
    lambda_environment_vars = {
                "ENV": "PROD" if environment == "production" else "STG",
                "YM_JOB_ENVIRONMENT": "production" if environment == "production" else "staging"
            }

    zipfile_obj = generate_zip(file_name)

    layers = [get_latest_lambda_layer_version(client, environment_abbreviation)['LayerVersionArn']]
    print(layers)
    client.create_function(
        FunctionName=name,
        Runtime='python3.8',
        Role=role,
        Handler='lambda_function.lambda_handler',
        Code={
            'ZipFile': zipfile_obj
        },
        Description='calls python code in dcs-api-endpoints',
        Timeout=timeout,
        MemorySize=memory,
        Publish=True,
        VpcConfig=json.loads(vpc_config),
        PackageType='Zip',
        # DeadLetterConfig={
        #     'TargetArn': 'string'
        # },
        Environment={
            'Variables': lambda_environment_vars
        },
        # KMSKeyArn='string',
        # TracingConfig={
        #     'Mode': 'Active' | 'PassThrough'
        # },
        # Tags={
        #     'string': 'string'
        # },
        Layers=layers,
        # FileSystemConfigs=[
        #     {
        #         'Arn': 'string',
        #         'LocalMountPath': 'string'
        #     },
        # ],
        # ImageConfig={
        #     'EntryPoint': [
        #         'string',
        #     ],
        #     'Command': [
        #         'string',
        #     ],
        #     'WorkingDirectory': 'string'
        # },
        # CodeSigningConfigArn='string'
    )


if __name__ == "__main__":
    """
    python3 deploy/upsert_lambda.py -f lambdas/somewhere/get/lambda_function.py -e staging
    """
    default_vpc = json.dumps({
        }
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file_name", required=True)
    parser.add_argument("-e", "--environment", default="staging")
    parser.add_argument("-t", "--timeout", default=30)
    parser.add_argument("-m", "--memory", default=128)
    parser.add_argument("-vpc", "--vpc_config", default=default_vpc)


    args = parser.parse_args()

    client = boto3.client("lambda")

    upsert_lambda(
        client,
        args.file_name,
        args.environment,
        args.timeout,
        args.memory,
        args.vpc_config
    )
