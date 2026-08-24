from aws_cdk import (
    Stack,
    aws_secretsmanager as secretsmanager,
    RemovalPolicy,
    aws_ec2 as ec2,
    CfnOutput,
    aws_rds as rds,
    aws_lambda as lambda_,
    Duration,
    CustomResource,
    Aws
)
from constructs import Construct


class PostgresConfigStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, pg_info: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, description="Creates postgres databases and tables for microservices", **kwargs)


        self.vpc = vpc

        self.pg_sg = ec2.SecurityGroup.from_security_group_id(
            scope=self,
            id="PGSecurityGroup",
            security_group_id=pg_info["security-group-id"]
        )

        self.pg_secret = secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id="PostgresSecret",
            secret_name=pg_info["secret-name"]
        )

        # Lambda function to create databases
        db_creator_lambda = lambda_.Function(self, "DBCreatorLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_inline('''
import json
import boto3
import psycopg2
import cfnresponse
from psycopg2 import sql


def handler(event, context):
    try:
        if event['RequestType'] == 'Delete':
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
            return
        
        secret_arn = event['ResourceProperties']['SecretArn']
        databases = event['ResourceProperties']['Databases']
        schemas = event['ResourceProperties']['Schemas']
        
        sm = boto3.client('secretsmanager')
        secret = json.loads(sm.get_secret_value(SecretId=secret_arn)['SecretString'])
        
        admin_conn = psycopg2.connect(
            host=secret['host'],
            port=secret['port'],
            user=secret['username'],
            password=secret['password'],
            database='postgres'
        )
        admin_conn.autocommit = True
        admin_cursor = admin_conn.cursor()
        
        for db in databases:
            admin_cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
            exists = admin_cursor.fetchone()

            if not exists:
                admin_cursor.execute(
                    sql.SQL("CREATE DATABASE {}")
                    .format(sql.Identifier(db))
                )
                print(f"Created database: {db}")
            else:
                print(f"Database already exists: {db}")

            if db == 'ecomm':
                db_conn = psycopg2.connect(
                    host=secret['host'],
                    port=secret['port'],
                    user=secret['username'],
                    password=secret['password'],
                    database=db
                )
                db_conn.autocommit = True
                db_cursor = db_conn.cursor()

                # Create application schemas
                for schema in schemas:
                    db_cursor.execute(
                        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")
                        .format(sql.Identifier(schema))
                    )
                db_cursor.close()
                                          
            db_conn.close()
        admin_cursor.close()
        admin_conn.close() 
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
                                          
    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(
            event,
            context,
            cfnresponse.FAILED,
            {"Message": str(e)}
        )
'''),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.pg_sg],
            timeout=Duration.minutes(5),
            layers=[
                lambda_.LayerVersion(
                    self, "Psycopg2Layer",
                    code=lambda_.Code.from_asset("lambda_layers/psycopg2"),
                    compatible_runtimes=[lambda_.Runtime.PYTHON_3_12]
                )
            ]
        )


        self.pg_secret.grant_read(db_creator_lambda)

        # Custom resource to trigger database and schema creation
        CustomResource(self, "DatabaseCreator",
            service_token=db_creator_lambda.function_arn,
            properties={
                "SecretArn": self.pg_secret.secret_arn,
                "Databases": ["ecomm"],
                "Schemas": ["ordering", "payment", "platform", "product", "rag", "security", "shipping", "web"]
            }
        )
