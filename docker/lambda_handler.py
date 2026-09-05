"""
AWS Lambda Handler for CAD Extractor IR.
Part of the La Vinci Project by Saikat Dutta Chowdhury.
"""

import os
import json
import boto3
from cad_extractor.core import extract_cad_ir

s3 = boto3.client("s3")

def handler(event, context):
    try:
        # Support both direct invocation and S3 Event triggers
        if "Records" in event:
            record = event["Records"][0]
            bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]
        else:
            bucket = event["bucket"]
            key = event["key"]

        local_dwg = f"/tmp/{os.path.basename(key)}"
        s3.download_file(bucket, key, local_dwg)

        # Execute extraction pipeline into La Vinci CAD IR
        ir = extract_cad_ir(local_dwg, dwg2dxf_binary="/usr/local/bin/dwg2dxf")

        # Save extracted IR back to S3
        output_key = key.rsplit(".", 1)[0] + "_ir.json"
        s3.put_object(
            Bucket=bucket,
            Key=output_key,
            Body=ir.model_dump_json(indent=2),
            ContentType="application/json",
            Metadata={
                "project": "La Vinci",
                "author": "Saikat Dutta Chowdhury",
                "format": "LAVINCI_CAD_IR_V1"
            }
        )

        return {
            "statusCode": 200,
            "status": "SUCCESS",
            "bucket": bucket,
            "input_dwg": key,
            "extracted_ir": output_key,
            "summary": {
                "components": ir.geometry_primitives.summary.total_components,
                "lines": ir.geometry_primitives.summary.total_lines,
                "layers": len(ir.layers)
            }
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "status": "ERROR",
            "error": str(e)
        }
